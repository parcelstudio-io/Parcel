"""PG-1 — execution-provider selection for the perception models.

Every cell here runs offline on a CUDA-less box: ``resolve_provider`` takes the
available execution providers and the filesystem probe as INJECTED arguments, so
the CUDA rows of the table are exercised on CI hardware that has no CUDA. That is
deliberate — a fallback policy that can only be tested on the one machine that
has the hardware is a policy nobody tests.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from parcel_robot.perception.providers import (
    KNOWN_PROVIDERS,
    MEASURED_PRECISION_QUALITY,
    PRECISION_QUALITY_CONFOUND,
    PRECISION_QUALITY_DOES_NOT_PROVE,
    PROVIDER_AUTO,
    PROVIDER_CPU_INT8,
    PROVIDER_CUDA_FP16,
    PROVIDER_ENV,
    PROVIDER_ORDER,
    ProviderNotHonouredError,
    assert_provider_honoured,
    log_resolution,
    requested_provider,
    resolve_provider,
)

INT8 = ("model_int8.onnx", "model.onnx")
FP16 = ("model_fp16.onnx",)

CUDA_BOX = ("TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider")
CPU_BOX = ("AzureExecutionProvider", "CPUExecutionProvider")

WD = Path("/nonexistent/weights")


def _resolve(*, providers, present, requested=None):
    """Resolve against a simulated machine: EP list + a set of on-disk filenames."""

    names = set(present)
    return resolve_provider(
        WD,
        int8_candidates=INT8,
        fp16_candidates=FP16,
        requested=requested,
        available_execution_providers=providers,
        file_exists=lambda p: p.name in names,
    )


# ---------------------------------------------------------------------------
# the fallback order itself
# ---------------------------------------------------------------------------


def test_the_documented_fallback_order_is_cuda_then_cpu() -> None:
    """The ORDER is the policy. Pinned so it cannot be reversed silently."""

    assert PROVIDER_ORDER == (PROVIDER_CUDA_FP16, PROVIDER_CPU_INT8)
    assert KNOWN_PROVIDERS == {PROVIDER_CUDA_FP16, PROVIDER_CPU_INT8}


def test_auto_takes_the_gpu_when_the_box_has_one() -> None:
    r = _resolve(providers=CUDA_BOX, present={"model_fp16.onnx", "model_int8.onnx"})
    assert r.selected == PROVIDER_CUDA_FP16
    assert r.precision == "fp16"
    assert r.model_file is not None and r.model_file.name == "model_fp16.onnx"
    assert r.execution_providers[0] == "CUDAExecutionProvider"
    assert r.is_gpu is True
    assert r.rejected == ()  # nothing was skipped, so nothing to report


# ---------------------------------------------------------------------------
# SEED TARGET: "fp16 path selected on a CUDA-less machine"
# ---------------------------------------------------------------------------


def test_a_cuda_less_machine_never_selects_fp16_even_with_the_fp16_file_present() -> None:
    """The whole "behaves exactly as today" guarantee.

    An fp16 artifact sitting on disk must not move a CPU-only box onto a path its
    onnxruntime cannot execute. Presence of weights is NOT capability.
    """

    r = _resolve(providers=CPU_BOX, present={"model_fp16.onnx", "model_int8.onnx"})
    assert r.selected == PROVIDER_CPU_INT8
    assert r.precision == "int8"
    assert r.model_file is not None and r.model_file.name == "model_int8.onnx"
    assert r.execution_providers == ("CPUExecutionProvider",)
    assert r.is_gpu is False


def test_a_cuda_less_machine_resolves_identically_whether_or_not_fp16_is_installed() -> None:
    """Byte-for-byte the same decision, so installing fp16 weights is inert on CPU."""

    with_fp16 = _resolve(providers=CPU_BOX, present={"model_fp16.onnx", "model_int8.onnx"})
    without = _resolve(providers=CPU_BOX, present={"model_int8.onnx"})
    assert with_fp16.selected == without.selected == PROVIDER_CPU_INT8
    assert with_fp16.model_file == without.model_file
    assert with_fp16.execution_providers == without.execution_providers


# ---------------------------------------------------------------------------
# SEED TARGET: "GPU path silently falls back without logging"
# ---------------------------------------------------------------------------


def test_falling_back_records_every_rejected_provider_with_a_reason() -> None:
    """A degrade must carry its own explanation, not just its outcome."""

    r = _resolve(providers=CPU_BOX, present={"model_int8.onnx"})
    assert r.selected == PROVIDER_CPU_INT8
    assert r.degraded is True
    assert [name for name, _ in r.rejected] == [PROVIDER_CUDA_FP16]
    (_, why), = r.rejected
    assert "CUDAExecutionProvider" in why and "not registered" in why
    # and the reason must survive into the single construction-time log line
    assert PROVIDER_CUDA_FP16 in r.describe()
    assert "rejected" in r.describe()


def test_a_gpu_box_missing_the_fp16_file_falls_back_and_says_so() -> None:
    r = _resolve(providers=CUDA_BOX, present={"model_int8.onnx"})
    assert r.selected == PROVIDER_CPU_INT8
    assert r.degraded is True
    (name, why), = r.rejected
    assert name == PROVIDER_CUDA_FP16
    assert "model_fp16.onnx" in why


def test_a_silent_degrade_is_impossible_because_the_log_level_escalates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """INFO for a clean pick, WARNING for a degrade, ERROR for a refusal.

    A fallback logged at INFO would vanish in a normal-verbosity run, which is
    exactly how a robot ends up running 35x slower than its operator believes.
    """

    clean = _resolve(providers=CUDA_BOX, present={"model_fp16.onnx"})
    degraded = _resolve(providers=CPU_BOX, present={"model_int8.onnx"})
    refused = _resolve(providers=CPU_BOX, present=set())

    levels = {}
    for label, resolution in (("clean", clean), ("degraded", degraded), ("refused", refused)):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="parcel_robot.perception.providers"):
            log_resolution(resolution, model="owlv2")
        assert len(caplog.records) == 1, f"{label}: expected exactly one line at construction"
        levels[label] = caplog.records[0].levelno
        assert "owlv2" in caplog.records[0].getMessage()

    assert levels["clean"] == logging.INFO
    assert levels["degraded"] == logging.WARNING
    assert levels["refused"] == logging.ERROR
    assert levels["degraded"] > levels["clean"]


# ---------------------------------------------------------------------------
# SEED TARGET: an explicit pin must REFUSE, never quietly degrade
# ---------------------------------------------------------------------------


def test_pinning_cuda_on_a_cpu_box_refuses_instead_of_degrading() -> None:
    """An operator who pinned the GPU has sized a loop around ~16 ms, not 560 ms."""

    r = _resolve(providers=CPU_BOX, present={"model_int8.onnx"}, requested=PROVIDER_CUDA_FP16)
    assert r.selected is None
    assert r.is_gpu is False
    assert "refusing to degrade silently" in r.reason
    assert r.rejected  # and it still says why


def test_pinning_cpu_int8_is_honoured_on_a_gpu_box() -> None:
    r = _resolve(
        providers=CUDA_BOX,
        present={"model_fp16.onnx", "model_int8.onnx"},
        requested=PROVIDER_CPU_INT8,
    )
    assert r.selected == PROVIDER_CPU_INT8
    assert r.model_file is not None and r.model_file.name == "model_int8.onnx"
    assert r.rejected == ()


def test_an_unknown_provider_value_refuses_rather_than_guessing() -> None:
    r = _resolve(providers=CUDA_BOX, present={"model_fp16.onnx"}, requested="cuda")
    assert r.selected is None
    assert PROVIDER_ENV in r.reason and "cuda" in r.reason


def test_no_weights_at_all_refuses_with_both_providers_explained() -> None:
    r = _resolve(providers=CUDA_BOX, present=set())
    assert r.selected is None
    assert [name for name, _ in r.rejected] == [PROVIDER_CUDA_FP16, PROVIDER_CPU_INT8]


def test_absent_onnxruntime_resolves_to_refusal_not_an_exception() -> None:
    r = _resolve(providers=(), present={"model_int8.onnx", "model_fp16.onnx"})
    assert r.selected is None


# ---------------------------------------------------------------------------
# SEED TARGET: registration is not execution
# ---------------------------------------------------------------------------


def test_a_cuda_session_that_ort_ran_on_the_cpu_is_refused() -> None:
    """The hole PG-1's own measurement found, closed.

    ``onnxruntime-gpu`` lists ``CUDAExecutionProvider`` in
    ``get_available_providers()`` even when its CUDA libraries are missing, then
    silently builds a CPU session. On this machine that produced an OWLv2 session
    labelled ``cuda_fp16`` running the fp16 graph on the CPU at 726 ms/query —
    slower than the 560 ms int8 CPU path it displaced, while every log line said
    "fp16". Resolution alone cannot catch it; only ``get_providers()`` can.
    """

    gpu = _resolve(providers=CUDA_BOX, present={"model_fp16.onnx"})
    assert gpu.selected == PROVIDER_CUDA_FP16

    with pytest.raises(ProviderNotHonouredError, match="NOT on the GPU"):
        assert_provider_honoured(gpu, ("CPUExecutionProvider",), model="owlv2")

    # honoured -> silent success
    assert_provider_honoured(
        gpu, ("CUDAExecutionProvider", "CPUExecutionProvider"), model="owlv2"
    )


def test_a_cpu_resolution_is_never_second_guessed() -> None:
    """The check applies to the GPU claim only; CPU sessions report CPU and that is right."""

    cpu = _resolve(providers=CPU_BOX, present={"model_int8.onnx"})
    assert_provider_honoured(cpu, ("CPUExecutionProvider",), model="owlv2")
    assert_provider_honoured(cpu, (), model="owlv2")


# ---------------------------------------------------------------------------
# the config surface
# ---------------------------------------------------------------------------


def test_the_default_request_mode_is_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROVIDER_ENV, raising=False)
    assert requested_provider() == PROVIDER_AUTO
    monkeypatch.setenv(PROVIDER_ENV, "   ")
    assert requested_provider() == PROVIDER_AUTO


def test_the_env_knob_selects_the_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROVIDER_ENV, "  CUDA_FP16 ")
    assert requested_provider() == PROVIDER_CUDA_FP16
    r = resolve_provider(
        WD,
        int8_candidates=INT8,
        fp16_candidates=FP16,
        available_execution_providers=CPU_BOX,
        file_exists=lambda p: p.name == "model_int8.onnx",
    )
    assert r.selected is None, "the env pin must reach resolution without being passed explicitly"


# ---------------------------------------------------------------------------
# SEED TARGET: "int8 quality regression unpinned"
# ---------------------------------------------------------------------------


def test_every_precision_row_carries_its_denominators() -> None:
    """A recall without its denominator is a vibe. All three rows must be arithmetic."""

    assert set(MEASURED_PRECISION_QUALITY) == {
        "int8_ort_cpu", "fp16_ort_cuda", "fp16_torch_cuda"
    }
    for name, row in MEASURED_PRECISION_QUALITY.items():
        assert row["ground_truth_instances"] == 298, name
        assert row["frames"] == 42, name
        assert row["source"], name
        tp = int(row["true_positives"])
        n_pred = int(row["predictions"])
        assert float(row["micro_recall"]) == pytest.approx(tp / 298), name
        assert float(row["precision"]) == pytest.approx(tp / n_pred), name


def test_the_int8_cost_is_PRECISION_and_that_survives_every_pairing() -> None:
    """The real, reproducible cost of the int8 fallback.

    int8 spends 243 predictions to find 43 objects; both fp16 paths spend 133-172
    to find 37-49. That deficit holds against fp16 under onnxruntime AND under
    torch, so it is a property of the precision rather than of a runtime.
    """

    int8 = MEASURED_PRECISION_QUALITY["int8_ort_cpu"]
    for other in ("fp16_ort_cuda", "fp16_torch_cuda"):
        assert float(int8["precision"]) < float(MEASURED_PRECISION_QUALITY[other]["precision"]), (
            f"int8 precision must be recorded as worse than {other}"
        )
    assert int(int8["predictions"]) > int(MEASURED_PRECISION_QUALITY["fp16_ort_cuda"]["predictions"])


def test_the_inherited_int8_recall_claim_is_recorded_as_NOT_reproducing() -> None:
    """PG-1 inherited "int8 costs recall (.144 vs .164)". Within one runtime it reverses.

    This is pinned because the wrong version of the claim is the one that
    propagates: it is short, quotable, and already in two documents. If a future
    edit "restores" it, the arithmetic here reddens.
    """

    int8 = MEASURED_PRECISION_QUALITY["int8_ort_cpu"]
    fp16_ort = MEASURED_PRECISION_QUALITY["fp16_ort_cuda"]
    fp16_torch = MEASURED_PRECISION_QUALITY["fp16_torch_cuda"]

    # same runtime: int8 recall is HIGHER, not lower
    assert int8["runtime"].split()[0] == fp16_ort["runtime"].split()[0] == "onnxruntime"
    assert float(int8["micro_recall"]) > float(fp16_ort["micro_recall"])

    # the .164 that the inherited claim compares against is torch's, not ORT's
    assert float(fp16_torch["micro_recall"]) == pytest.approx(0.1644, abs=1e-4)
    assert "torch" in str(fp16_torch["runtime"])
    # and the two fp16 rows disagree materially on the SAME frames
    assert int(fp16_torch["true_positives"]) != int(fp16_ort["true_positives"])


def test_the_confound_and_the_does_not_prove_are_stated_in_the_tree() -> None:
    assert "RUNTIME" in PRECISION_QUALITY_CONFOUND
    assert "REVERSES" in PRECISION_QUALITY_CONFOUND
    assert "onnxruntime" in PRECISION_QUALITY_CONFOUND and "torch" in PRECISION_QUALITY_CONFOUND
    # the scene caveat that makes every one of these numbers sim-only
    assert "0/69" in PRECISION_QUALITY_DOES_NOT_PROVE
    assert "city_block.xml" in PRECISION_QUALITY_DOES_NOT_PROVE
