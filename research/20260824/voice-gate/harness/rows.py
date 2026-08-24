#!/usr/bin/env python
"""Turning a list of admissions into the pre-registered rows, once, for every arm.

Scoring lives away from the runner so that arm (a) and arm (e) are scored by
identical code; a row that means something different per arm is not a row.
"""

from __future__ import annotations

import numpy as np

from .gate import Admission, FakeTransport, Tape

#: gpt-realtime-2.1-mini, the card H1 priced every live run against
#: (``realtime/cost.py``: audio in $10/Mtok, audio out $20/Mtok) at H1's
#: measured 10 audio tokens per second.
AUDIO_TOKENS_PER_SECOND = 10.0
USD_PER_UPLOADED_SECOND = AUDIO_TOKENS_PER_SECOND * 10.00 / 1e6
USD_PER_RESPONSE_SECOND = AUDIO_TOKENS_PER_SECOND * 20.00 / 1e6
#: H1's measured mean spoken response length on the corpus day.
RESPONSE_SECONDS = 3.0


def overlaps(admission: Admission, start_s: float, end_s: float) -> bool:
    return admission.open_s <= end_s and admission.close_s >= start_s


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else float("nan")


def score(tape: Tape, admissions: list[Admission], transport: FakeTransport, role: str) -> dict:
    """Per-role: how many of these stimuli got through, and what it would cost."""

    targets = [placement for placement in tape.placements if placement.role == role]
    accepted = 0
    per_geometry: dict[str, list[int]] = {}
    for placement in targets:
        hit = any(
            admission.admitted
            and overlaps(admission, placement.speech_start_s, placement.speech_end_s)
            for admission in admissions
        )
        accepted += int(hit)
        per_geometry.setdefault(placement.geometry, []).append(int(hit))
    hours = tape.seconds / 3600.0
    admitted = [admission for admission in admissions if admission.admitted]
    uploaded_s = sum(admission.uploaded_seconds for admission in admitted)
    return {
        "role": role,
        "trials": len(targets),
        "accepted": accepted,
        "acceptance_rate": accepted / len(targets) if targets else float("nan"),
        "per_geometry": {
            key: {"n": len(values), "accepted": int(sum(values)),
                  "rate": float(np.mean(values))}
            for key, values in sorted(per_geometry.items())
        },
        "tape_seconds": tape.seconds,
        "spans_considered": len(admissions),
        "spans_admitted": len(admitted),
        "opens_per_hour": len(admitted) / hours if hours else float("nan"),
        "uploaded_seconds": uploaded_s,
        "uploaded_bytes": sum(admission.uploaded_bytes for admission in admitted),
        "uploaded_bytes_by_role": dict(transport.by_role),
        "uploaded_seconds_per_hour": uploaded_s / hours if hours else float("nan"),
        "projected_usd_per_hour": (
            uploaded_s * USD_PER_UPLOADED_SECOND
            + len(admitted) * RESPONSE_SECONDS * USD_PER_RESPONSE_SECOND
        )
        / (hours or float("nan")),
    }


def owner_quality(
    tape: Tape, admissions: list[Admission], roles: tuple[str, ...] = ("owner",)
) -> dict:
    """First-word loss, endpoint and admission latency on the owner's own turns.

    ``roles`` exists for arm (c): a wake-phrase policy's committed turns are the
    ones carrying the phrase, and the owner tape (real human speech that never
    says "hey Parcel") is the wrong denominator for it.
    """

    truncations: list[float] = []
    endpoints: list[float] = []
    decisions: list[float] = []
    lost = 0
    considered = 0
    for placement in tape.placements:
        if not placement.role.startswith(roles):
            continue
        for admission in admissions:
            if not admission.admitted:
                continue
            if not overlaps(admission, placement.speech_start_s, placement.speech_end_s):
                continue
            considered += 1
            truncation = admission.upload_from_s - placement.speech_start_s
            truncations.append(truncation)
            lost += int(truncation > 0.0)
            endpoints.append(admission.close_s - placement.speech_end_s)
            decisions.append(admission.decided_s - placement.speech_start_s)
            break
    return {
        "n": considered,
        "first_word_lost": lost,
        "first_word_loss_rate": lost / considered if considered else float("nan"),
        "truncation_ms_p50": percentile([value * 1000.0 for value in truncations], 50),
        "truncation_ms_max": max([value * 1000.0 for value in truncations], default=float("nan")),
        "endpoint_s_p50": percentile(endpoints, 50),
        "endpoint_s_p95": percentile(endpoints, 95),
        "admission_latency_s_p50": percentile(decisions, 50),
        "admission_latency_s_p95": percentile(decisions, 95),
    }


__all__ = [
    "AUDIO_TOKENS_PER_SECOND",
    "RESPONSE_SECONDS",
    "USD_PER_RESPONSE_SECOND",
    "USD_PER_UPLOADED_SECOND",
    "overlaps",
    "owner_quality",
    "percentile",
    "score",
]
