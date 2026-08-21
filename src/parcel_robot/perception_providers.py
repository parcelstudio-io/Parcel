"""Execution-provider selection for the perception models (card PG-1).

Why this module exists
----------------------
The incumbent OWLv2 / SigLIP-2 paths hard-coded ``providers=["CPUExecutionProvider"]``
and an int8 ONNX artifact. That choice was correct when it was made — the
``scripts/fetch_owlv2.sh`` header records the reasoning: *"onnxruntime here is
CPU-only (providers: CPU + Azure; NO CUDAExecutionProvider) ... fp16 pays off only
on GPU, which onnxruntime cannot reach here."* The 2026-08-21 perception bench
(``scrum/20260821/perception/bench_detectors.md``) measured what that costs:
**560 ms/query, 1.8 Hz** — not loop-capable. PG-1 re-measured the same 42 frames
through *this repo's own detector* under onnxruntime and found **524 ms on
cpu_int8 vs 83 ms on cuda_fp16 (6.3x)**, plus a precision cost to int8 that is
recorded in :data:`MEASURED_PRECISION_QUALITY` (int8 spends 243 predictions to
find 43 objects; fp16 spends 133 to find 37).

This module turns that hard-coded choice into a **resolved, logged, auditable
decision** with a documented fallback order, without changing a single caller:
:class:`ProviderResolution` is what the detector/embedder constructors consult.

The fallback order
------------------
``PROVIDER_ORDER`` is ``(cuda_fp16, cpu_int8)`` — try the GPU fp16 graph, fall
back to the CPU int8 graph. Three request modes, selected by
:data:`PROVIDER_ENV` (default ``auto``):

``auto``
    Walk ``PROVIDER_ORDER``; take the first provider whose execution provider is
    registered in this ``onnxruntime`` build **and** whose ONNX artifact is on
    disk. A machine without CUDA therefore resolves to ``cpu_int8`` and behaves
    **exactly as today** — same artifact, same execution provider, same numbers.

``cuda_fp16`` / ``cpu_int8`` (explicit pin)
    Use exactly that provider or **refuse to construct** (``selected is None``).

Why an explicit pin refuses instead of degrading — the fail-closed argument
--------------------------------------------------------------------------
Silent degrade is the dangerous outcome here, not loud failure. An operator who
pinned ``cuda_fp16`` has sized a control loop around ~83 ms of detector latency.
If that silently became the 524 ms CPU int8 path, the loop would miss its budget
by **6.3x** while every log line still said "detector running". Refusing to
construct surfaces the misconfiguration at startup, where a human is watching,
instead of at 1.9 Hz in the field. ``auto`` is the mode that degrades, and it
degrades *loudly*: every rejected provider is recorded in
:attr:`ProviderResolution.rejected` with its reason and logged once at
construction, and :func:`assert_provider_honoured` additionally refuses a session
that onnxruntime accepted as CUDA and then ran on the CPU.

What this module deliberately does NOT do
-----------------------------------------
It does not import ``onnxruntime``, touch the GPU, or read the filesystem on its
own behalf. ``available_execution_providers`` and ``file_exists`` are injected,
so the whole resolution table — including "what happens on a CUDA machine" — is
testable on a machine with no CUDA at all, which is the only way this logic can
be pinned in a CI tier that must stay offline and deterministic.

HONESTY (P0)
------------
Selecting ``cuda_fp16`` changes latency and numerics (fp16 vs int8), not the
world the model looks at. The 2026-08-21 bench measured **0/69 person recall on
Parcel renders vs 127/156 on real photos** for this same OWLv2 checkpoint: the
scene has no visual semantics to generalize from. No recall, precision, or
field-recognition claim follows from moving this model to the GPU. What follows
is a latency claim, and only on the frames it was measured on.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: Provider identifiers. These name a (execution provider, ONNX artifact
#: precision) PAIR, because on this stack the two are not independent: fp16 is a
#: poor CPU choice (x86 lacks native fp16 matmul, so ORT up-casts and you pay the
#: memory without the speed) and int8 QDQ is a poor CUDA choice (the CUDA EP
#: falls back to CPU for most quantized ops). Naming the pair keeps a caller from
#: composing the two nonsensical combinations.
PROVIDER_CUDA_FP16 = "cuda_fp16"
PROVIDER_CPU_INT8 = "cpu_int8"

#: The documented fallback order. Index 0 is attempted first. This tuple IS the
#: policy — tests assert against it so the order cannot drift silently.
PROVIDER_ORDER: tuple[str, ...] = (PROVIDER_CUDA_FP16, PROVIDER_CPU_INT8)

#: Request mode meaning "walk PROVIDER_ORDER and take the first that works".
PROVIDER_AUTO = "auto"

KNOWN_PROVIDERS: frozenset[str] = frozenset(PROVIDER_ORDER)

#: Config surface. One env knob, shared by every perception model, so the whole
#: stack moves together instead of drifting per-model.
PROVIDER_ENV = "PARCEL_PERCEPTION_PROVIDER"

#: onnxruntime execution-provider names, per provider id.
_EXECUTION_PROVIDERS: dict[str, tuple[str, ...]] = {
    # CPUExecutionProvider is kept as the CUDA EP's in-session fallback for the
    # handful of ops the CUDA EP does not implement. That is ORT-internal op
    # placement inside one session, NOT the cross-provider degrade this module
    # governs: the session is still a CUDA session and still reports as such.
    PROVIDER_CUDA_FP16: ("CUDAExecutionProvider", "CPUExecutionProvider"),
    PROVIDER_CPU_INT8: ("CPUExecutionProvider",),
}

_PRECISION: dict[str, str] = {
    PROVIDER_CUDA_FP16: "fp16",
    PROVIDER_CPU_INT8: "int8",
}

#: The int8 fallback is not merely slower — it is measurably WORSE on precision,
#: and that cost is recorded here rather than left in prose, so a fallback can
#: never be read as free.
#:
#: All three rows: OWLv2-base-patch16-ensemble, the SAME 42 rendered frames of
#: ``city_block.xml``, 11 query labels, 298 ground-truth instances, per-label
#: greedy matching at IoU >= 0.5, score threshold 0.1. Only the runtime and the
#: numeric precision differ. ``int8_ort_cpu`` and ``fp16_ort_cuda`` were measured
#: by PG-1 through the repo's own ``OwlV2Detector``; ``fp16_torch_cuda`` is the
#: inherited 2026-08-21 bench row, kept because it is where the "int8 costs
#: quality" claim came from and because the disagreement is the point.
MEASURED_PRECISION_QUALITY: dict[str, dict[str, object]] = {
    "int8_ort_cpu": {
        "micro_recall": 0.14429530201342283,  # 43 / 298
        "macro_recall": 0.1652097902097902,
        "precision": 0.17695473251028807,  # 43 / 243
        "true_positives": 43,
        "predictions": 243,
        "ground_truth_instances": 298,
        "frames": 42,
        "runtime": "onnxruntime CPUExecutionProvider",
        "source": "PG1_STATUS.md (reproduces bench_detectors.md incumbent row exactly)",
    },
    "fp16_ort_cuda": {
        "micro_recall": 0.12416107382550336,  # 37 / 298
        "macro_recall": 0.16515151515151516,
        "precision": 0.2781954887218045,  # 37 / 133
        "true_positives": 37,
        "predictions": 133,
        "ground_truth_instances": 298,
        "frames": 42,
        "runtime": "onnxruntime CUDAExecutionProvider",
        "source": "PG1_STATUS.md (scrum/20260821/task_6)",
    },
    "fp16_torch_cuda": {
        "micro_recall": 0.1644295302013423,  # 49 / 298
        "macro_recall": 0.17564102564102566,
        "precision": 0.28488372093023256,  # 49 / 172
        "true_positives": 49,
        "predictions": 172,
        "ground_truth_instances": 298,
        "frames": 42,
        "runtime": "torch 2.13.0+cu130 CUDA",
        "source": "scrum/20260821/perception/bench_detectors.md (results/gpu_owlv2_fp16.json)",
    },
}

#: What the three rows actually say, written down because the inherited one-line
#: version of this claim is WRONG and would otherwise keep propagating.
#:
#: The PG-1 card and the bench both state "int8 costs quality too (.144 vs .164
#: recall vs fp16)". Measured INSIDE one runtime that does not reproduce: under
#: onnxruntime, int8 has HIGHER micro-recall than fp16 (.1443 vs .1242). The .164
#: figure is torch's, and torch fp16 and the fp16 ONNX export are not the same
#: numbers — 49 vs 37 true positives on identical frames.
#:
#: What DOES hold on every measurement, and is the real cost of the int8 fallback:
#: **precision**. int8 emits 243 predictions to find 43 objects (.177); both fp16
#: paths emit 133-172 to find 37-49 (.278-.285). int8 is ~1.6x noisier per true
#: positive. For a stack whose next card (PG-3) is calibrated abstention, a
#: precision deficit is the expensive kind of error, not the cheap kind.
PRECISION_QUALITY_CONFOUND = (
    "The inherited 'int8 costs recall' comparison confounds precision with RUNTIME: "
    "int8 was measured under onnxruntime-CPU and fp16 under torch-CUDA. Measured "
    "within onnxruntime alone the recall direction REVERSES (int8 .1443 vs fp16 "
    ".1242); what survives every pairing is int8's precision deficit (.177 vs "
    ".278-.285). Same 42 frames, 11 labels, 298 GT instances, IoU>=0.5, threshold 0.1."
)

#: HONESTY (P0): every row above is a SIM number on a scene with no visual
#: semantics. Person recall is 0/69 for all three precisions — the scene, not the
#: precision, is why (bench_detectors.md: 127/156 on real photos, same checkpoint).
#: These are precision-vs-precision deltas on identical pixels with identical
#: matching code. Nothing here is a field-recognition claim, and none of it
#: transfers to a D455.
PRECISION_QUALITY_DOES_NOT_PROVE = (
    "All precision-quality rows are sim numbers on city_block.xml, which has 48 "
    "material references and zero texture images. Person recall is 0/69 under every "
    "precision. These deltas rank precisions against each other on THIS scene; they "
    "say nothing about real-world recognition."
)


@dataclass(frozen=True, slots=True)
class ProviderResolution:
    """The outcome of provider selection — the thing that gets logged once.

    ``selected is None`` means **refuse to construct**: the caller returns its
    "model unavailable" value (``None``) exactly as it does for absent weights.
    ``rejected`` carries every provider that was considered and why, so a
    degraded run is never a mystery weeks later.
    """

    requested: str
    selected: str | None
    execution_providers: tuple[str, ...] = ()
    model_file: Path | None = None
    precision: str = ""
    reason: str = ""
    rejected: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def is_gpu(self) -> bool:
        return self.selected == PROVIDER_CUDA_FP16

    @property
    def degraded(self) -> bool:
        """True when ``auto`` fell back past a higher-priority provider."""

        return bool(self.rejected) and self.selected is not None

    def describe(self) -> str:
        """One dense line naming the live path and every rejection."""

        head = (
            f"perception provider: requested={self.requested} "
            f"selected={self.selected or 'NONE (refused)'} "
            f"precision={self.precision or '-'} "
            f"ep={'+'.join(self.execution_providers) or '-'} "
            f"model={self.model_file.name if self.model_file else '-'}"
        )
        if self.reason:
            head += f" ({self.reason})"
        if self.rejected:
            trail = "; ".join(f"{name}: {why}" for name, why in self.rejected)
            head += f" | rejected: {trail}"
        return head


#: Per provider, the ONNX filenames to look for, in preference order. The int8
#: candidates match the incumbent loaders byte-for-byte so ``cpu_int8`` picks the
#: exact artifact the repo runs today.
def _model_candidates(provider: str, int8_candidates: Sequence[str], fp16_candidates: Sequence[str]) -> tuple[str, ...]:
    if provider == PROVIDER_CUDA_FP16:
        return tuple(fp16_candidates)
    return tuple(int8_candidates)


def requested_provider(override: str | None = None) -> str:
    """The configured request mode: ``auto`` (default), or an explicit pin.

    An unrecognised value is a configuration error, and configuration errors in
    a fail-closed system must not resolve to "whatever is convenient" — it maps
    to a request that no provider satisfies, so construction refuses and the
    reason names the bad value.
    """

    raw = (override if override is not None else os.environ.get(PROVIDER_ENV, "")).strip().lower()
    if not raw:
        return PROVIDER_AUTO
    return raw


def resolve_provider(
    weights_dir: Path,
    *,
    int8_candidates: Sequence[str],
    fp16_candidates: Sequence[str],
    requested: str | None = None,
    available_execution_providers: Sequence[str] | None = None,
    file_exists: Callable[[Path], bool] | None = None,
) -> ProviderResolution:
    """Resolve which (execution provider, artifact) pair this model will run on.

    ``available_execution_providers`` and ``file_exists`` are injected so the
    full table — including the CUDA rows — is exercisable on a CUDA-less CI box.
    When omitted they are read from the live ``onnxruntime`` build and the real
    filesystem.
    """

    req = requested_provider(requested)
    if available_execution_providers is None:
        available_execution_providers = _live_execution_providers()
    if file_exists is None:
        file_exists = Path.is_file
    available = set(available_execution_providers)

    if req == PROVIDER_AUTO:
        order: tuple[str, ...] = PROVIDER_ORDER
    elif req in KNOWN_PROVIDERS:
        order = (req,)
    else:
        return ProviderResolution(
            requested=req,
            selected=None,
            reason=(
                f"unknown {PROVIDER_ENV}={req!r}; "
                f"expected {PROVIDER_AUTO!r} or one of {sorted(KNOWN_PROVIDERS)}"
            ),
        )

    rejected: list[tuple[str, str]] = []
    for provider in order:
        needed = _EXECUTION_PROVIDERS[provider]
        primary = needed[0]
        if primary not in available:
            rejected.append((provider, f"{primary} not registered in this onnxruntime build"))
            continue
        names = _model_candidates(provider, int8_candidates, fp16_candidates)
        found = next((weights_dir / n for n in names if file_exists(weights_dir / n)), None)
        if found is None:
            rejected.append((provider, f"no {'/'.join(names)} under {weights_dir}"))
            continue
        return ProviderResolution(
            requested=req,
            selected=provider,
            execution_providers=needed,
            model_file=found,
            precision=_PRECISION[provider],
            reason=("first available in fallback order" if req == PROVIDER_AUTO else "explicitly pinned"),
            rejected=tuple(rejected),
        )

    if req != PROVIDER_AUTO:
        why = rejected[0][1] if rejected else "unavailable"
        return ProviderResolution(
            requested=req,
            selected=None,
            reason=f"{PROVIDER_ENV}={req} was pinned but is unavailable ({why}); refusing to degrade silently",
            rejected=tuple(rejected),
        )
    return ProviderResolution(
        requested=req,
        selected=None,
        reason="no provider in the fallback order is available",
        rejected=tuple(rejected),
    )


def prepare_cuda_runtime(resolution: ProviderResolution) -> None:
    """Make onnxruntime's CUDA libraries findable before a CUDA session is built.

    MEASURED on this machine, and non-obvious enough to be worth the code: when
    the CUDA/cuDNN runtime comes from pip wheels (``nvidia-cublas``,
    ``nvidia-cudnn-cu13``, ...) rather than a system CUDA install, onnxruntime
    does **not** find them on its own. ``libcublasLt.so.13`` fails to load,
    ``CUDAExecutionProvider`` is dropped, and the session silently becomes a CPU
    session — while ``get_available_providers()`` still advertises CUDA.

    ``onnxruntime.preload_dlls()`` adds the wheel library directories before the
    provider library is loaded and fixes it. Verified both ways on this box:

        without preload_dlls() -> get_providers() == ['CPUExecutionProvider']
        with    preload_dlls() -> get_providers() == ['CUDAExecutionProvider', ...]

    Best-effort by design: it is a no-op for a CPU resolution, and any failure is
    logged and swallowed because :func:`assert_provider_honoured` is the thing
    that actually enforces the outcome.
    """

    if not resolution.is_gpu:
        return
    try:
        import onnxruntime as ort
    except Exception:  # noqa: BLE001
        return
    preload = getattr(ort, "preload_dlls", None)
    if preload is None:
        logger.debug("onnxruntime has no preload_dlls(); relying on the system library path")
        return
    try:
        preload()
    except Exception as exc:  # noqa: BLE001 — assert_provider_honoured is the real gate
        logger.warning("onnxruntime.preload_dlls() failed (%s: %s)", type(exc).__name__, exc)


class ProviderNotHonouredError(RuntimeError):
    """onnxruntime accepted a CUDA session request and then ran it on the CPU.

    This is NOT hypothetical — it was hit on this machine during PG-1's own
    measurement pass. ``onnxruntime-gpu`` registers ``CUDAExecutionProvider`` in
    ``get_available_providers()`` from a stub library, so resolution legitimately
    selects it; the provider then fails to load its real backend at session
    construction (here: ``libcublasLt.so.13`` absent) and ORT **falls back to
    CPU with a warning and no error**. The measured result was a session
    reporting ``cuda_fp16`` while running the fp16 graph on the CPU at 726 ms —
    45x its GPU budget, with every log line still saying "fp16".

    Registration is therefore not execution, and the only safe reading of
    ``get_providers()`` disagreeing with the request is: refuse.
    """


def assert_provider_honoured(
    resolution: ProviderResolution, honoured: Sequence[str], *, model: str
) -> None:
    """Fail closed when ORT did not actually give us the provider we resolved.

    Called by every model constructor immediately after the session is built.
    Raises :class:`ProviderNotHonouredError`, which the loaders convert into
    their existing "model unavailable" (``None``) degrade — so a caller sees the
    same fail-closed outcome as absent weights, never a silent 45x slowdown.
    """

    if not resolution.is_gpu:
        return
    if "CUDAExecutionProvider" in tuple(honoured):
        return
    raise ProviderNotHonouredError(
        f"[{model}] resolved {resolution.selected} but onnxruntime honoured "
        f"{tuple(honoured)} — the session is NOT on the GPU. Refusing rather than "
        "running the fp16 graph on the CPU (measured 726 ms/query, vs 560 ms for the "
        "int8 CPU path it would have displaced). Check the CUDA/cuDNN runtime "
        "libraries onnxruntime-gpu needs."
    )


def _live_execution_providers() -> tuple[str, ...]:
    """Execution providers registered in the installed onnxruntime, or ``()``.

    Absent/broken onnxruntime is not an error here — it resolves to "no provider
    available", which the loaders already handle as "model unavailable".
    """

    try:
        import onnxruntime as ort
    except Exception:  # noqa: BLE001 — absent ORT is a degrade, never a crash
        return ()
    try:
        return tuple(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        return ()


def log_resolution(resolution: ProviderResolution, *, model: str) -> None:
    """Log the resolved path exactly once, at construction.

    Level is chosen so a degrade cannot hide in DEBUG: a clean resolution is
    INFO, a fallback past a higher-priority provider is WARNING, and a refusal
    is ERROR.
    """

    line = f"[{model}] {resolution.describe()}"
    if resolution.selected is None:
        logger.error("%s", line)
    elif resolution.degraded:
        logger.warning("%s", line)
    else:
        logger.info("%s", line)


__all__ = [
    "KNOWN_PROVIDERS",
    "MEASURED_PRECISION_QUALITY",
    "PRECISION_QUALITY_CONFOUND",
    "PRECISION_QUALITY_DOES_NOT_PROVE",
    "PROVIDER_AUTO",
    "PROVIDER_CPU_INT8",
    "PROVIDER_CUDA_FP16",
    "PROVIDER_ENV",
    "PROVIDER_ORDER",
    "ProviderNotHonouredError",
    "ProviderResolution",
    "assert_provider_honoured",
    "log_resolution",
    "prepare_cuda_runtime",
    "requested_provider",
    "resolve_provider",
]
