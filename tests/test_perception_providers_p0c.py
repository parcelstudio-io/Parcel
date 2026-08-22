"""P0-C — the GPU detector in the PRODUCTION venv.

PG-1 proved the CUDA fp16 path in a scratch venv (`~/.cache/parcel-pg1/gpuvenv`)
and left three things owner-gated: the dependency, the fp16 weights, and the
fetch scripts that land them. This card takes those three. The cells here pin the
parts of that promotion that a later reader could otherwise undo without noticing:

* the ``perception`` extra must keep the ``[cuda,cudnn]`` runtime extras — without
  them ``onnxruntime-gpu`` still ADVERTISES ``CUDAExecutionProvider`` and then
  silently builds a CPU session (PG-1 measured that failure at 726 ms/query while
  every log line said "fp16"). Reproduced on THIS venv on 2026-08-22:
  ``no preload_dlls -> ['CPUExecutionProvider']`` vs
  ``with preload_dlls -> ['CUDAExecutionProvider', 'CPUExecutionProvider']``.
* every fp16 filename the loaders probe must be fetchable — a candidate name with
  no ``--fp16`` row in the fetch script is a GPU path nobody can install.
* a session ORT did not honour must degrade the LOADER to ``None``. PG-1 pinned
  ``assert_provider_honoured`` as a function; nothing pinned that the loaders
  actually convert it into their "model unavailable" return.

Everything below runs offline on a CUDA-less box: the execution-provider list is
INJECTED. The two cells that touch the real weights cache skip when it is absent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import tomllib

from parcel_robot.detection_adapter import owlv2_onnx
from parcel_robot.detection_adapter.owlv2_onnx import (
    _MODEL_ONNX_CANDIDATES,
    _MODEL_ONNX_FP16_CANDIDATES,
    default_weights_dir,
    load_owlv2_detector,
    resolve_owlv2_provider,
)
from parcel_robot.instructnav import siglip2_onnx
from parcel_robot.instructnav.siglip2_onnx import (
    _TEXT_ONNX_CANDIDATES,
    _TEXT_ONNX_FP16_CANDIDATES,
    _VISION_ONNX_CANDIDATES,
    _VISION_ONNX_FP16_CANDIDATES,
    load_onnx_embedder,
    resolve_text_provider,
    resolve_vision_provider,
)
from parcel_robot.perception_providers import (
    PROVIDER_CPU_INT8,
    PROVIDER_CUDA_FP16,
    PROVIDER_ENV,
    ProviderNotHonouredError,
    assert_provider_honoured,
)

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
FETCH_OWLV2 = REPO / "scripts" / "fetch_owlv2.sh"
FETCH_SIGLIP2 = REPO / "scripts" / "fetch_siglip2.sh"

#: A machine with a working CUDA build, and one without. Injected, never probed.
CUDA_BOX = ("TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider")
CPU_BOX = ("AzureExecutionProvider", "CPUExecutionProvider")

SIGLIP2_DIR = Path.home() / ".cache" / "parcel" / "siglip2-b16"

#: ONNX files are protobuf; every export in use here starts with field 1 (ir_version)
#: as a varint, i.e. byte 0x08. Cheap "is this actually a model" probe that does not
#: read 300 MB or import onnx.
_ONNX_MAGIC = b"\x08"


# ---------------------------------------------------------------------------
# 1. the dependency is declared, WITH the runtime extras that make it real
# ---------------------------------------------------------------------------


def _perception_extra() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text())
    extras = data["project"]["optional-dependencies"]
    assert "perception" in extras, (
        "pyproject declares no `perception` extra; the GPU detector is then "
        "undeclared and `pip install -e '.[perception]'` cannot reproduce this venv"
    )
    return list(extras["perception"])


def test_the_perception_extra_declares_onnxruntime_gpu() -> None:
    reqs = _perception_extra()
    gpu = [r for r in reqs if r.split("[")[0].split(">")[0].split("=")[0].strip() == "onnxruntime-gpu"]
    assert gpu, f"`perception` extra does not name onnxruntime-gpu: {reqs}"


def test_the_perception_extra_keeps_the_cuda_and_cudnn_runtime_extras() -> None:
    """Without these the CUDA EP registers from a stub and the session runs on CPU.

    This is not style. Measured on this host, twice (PG-1 2026-08-21 and P0-C
    2026-08-22): the bare wheel fails to load ``libcublasLt.so.13`` at session
    construction and ORT falls back to CPU *with a warning and no error*. The
    ``cuda``/``cudnn`` extras pull the nvidia-* wheels that
    ``prepare_cuda_runtime()`` then exposes via ``onnxruntime.preload_dlls()``.
    """

    reqs = _perception_extra()
    spec = next(r for r in reqs if r.startswith("onnxruntime-gpu"))
    inside = spec.partition("[")[2].partition("]")[0]
    declared = {part.strip() for part in inside.split(",") if part.strip()}
    assert {"cuda", "cudnn"} <= declared, (
        f"onnxruntime-gpu is declared as {spec!r} — without the [cuda,cudnn] extras "
        "pip installs no CUDA runtime, CUDAExecutionProvider registers from a stub, "
        "and every session silently becomes a CPU session."
    )


def test_the_perception_extra_floors_at_the_version_proved_on_this_host() -> None:
    """1.28.0 is the version PG-1 measured 83 ms p50 on; nothing older is proved."""

    spec = next(r for r in _perception_extra() if r.startswith("onnxruntime-gpu"))
    assert ">=1.28" in spec, f"{spec!r} admits onnxruntime-gpu builds nobody measured here"


# ---------------------------------------------------------------------------
# 2. every fp16 artifact the loaders probe is actually fetchable
# ---------------------------------------------------------------------------

#: (fetch script, the fp16 filenames the matching loader probes)
_FP16_SOURCES = [
    (FETCH_OWLV2, _MODEL_ONNX_FP16_CANDIDATES),
    (FETCH_SIGLIP2, _TEXT_ONNX_FP16_CANDIDATES + _VISION_ONNX_FP16_CANDIDATES),
]


@pytest.mark.parametrize(("script", "names"), _FP16_SOURCES, ids=lambda v: getattr(v, "name", ""))
def test_every_fp16_candidate_is_pinned_by_its_fetch_script(script: Path, names) -> None:
    """A candidate filename with no fetch row is a GPU path nobody can install.

    The sha VALUE is deliberately not frozen here — the script owns the pin and
    duplicating it in the test tree just makes a legitimate re-export a two-file
    edit. What is pinned is the LINKAGE: the loader's filename, an `onnx/<name>`
    hub path, and *a* 64-hex sha256 next to it.
    """

    text = script.read_text()
    assert "--fp16" in text, f"{script.name} has no --fp16 mode"
    for name in names:
        row = re.search(rf'^\s*"{re.escape(name)}\|onnx/{re.escape(name)}\|([0-9a-f]{{64}})"',
                        text, re.MULTILINE)
        assert row, (
            f"{script.name} does not pin {name} — the loader probes it as an fp16 "
            "candidate, so a CUDA box would resolve to a file no script can fetch"
        )


@pytest.mark.parametrize(("script", "names"), _FP16_SOURCES, ids=lambda v: getattr(v, "name", ""))
def test_the_fp16_rows_are_additive_and_never_displace_the_int8_pins(script: Path, names) -> None:
    """The CPU fallback must keep its artifact: --fp16 ADDS, it does not swap.

    If ``--fp16`` ever replaced the int8 rows, a GPU box would stop holding the
    file its own ``cpu_int8`` fallback resolves to, and the documented fallback
    order would have nothing to fall back to.
    """

    text = script.read_text()
    int8_names = (
        (_MODEL_ONNX_CANDIDATES[0],) if script is FETCH_OWLV2
        else (_TEXT_ONNX_CANDIDATES[0], _VISION_ONNX_CANDIDATES[0])
    )
    for name in int8_names:
        assert re.search(rf'^\s*"{re.escape(name)}\|onnx/{re.escape(name)}\|[0-9a-f]{{64}}"',
                         text, re.MULTILINE), f"{script.name} lost its int8 pin for {name}"
    assert "FILES+=(" in text, f"{script.name}'s --fp16 does not append to FILES"


# ---------------------------------------------------------------------------
# 3. fp16 artifact probe — only when the cache actually holds them
# ---------------------------------------------------------------------------

_OWLV2_FP16 = default_weights_dir() / _MODEL_ONNX_FP16_CANDIDATES[0]
_SIGLIP_FP16 = [SIGLIP2_DIR / _TEXT_ONNX_FP16_CANDIDATES[0],
                SIGLIP2_DIR / _VISION_ONNX_FP16_CANDIDATES[0]]

_INSTALLED = [p for p in [_OWLV2_FP16, *_SIGLIP_FP16] if p.is_file()]


@pytest.mark.skipif(not _INSTALLED, reason="no fp16 artifacts installed (run fetch_*.sh --fp16)")
@pytest.mark.parametrize("path", _INSTALLED, ids=lambda p: p.name)
def test_an_installed_fp16_artifact_is_a_real_onnx_of_a_plausible_size(path: Path) -> None:
    assert path.stat().st_size > 100 * 1024 * 1024, (
        f"{path} is {path.stat().st_size} B — too small to be a base-16 fp16 export; "
        "a truncated download would otherwise be discovered at session build time"
    )
    with path.open("rb") as fh:
        assert fh.read(1) == _ONNX_MAGIC, f"{path} does not start like an ONNX protobuf"


@pytest.mark.skipif(not _OWLV2_FP16.is_file(), reason="owlv2 fp16 artifact not installed")
def test_a_cuda_box_resolves_to_the_file_the_fetch_script_actually_wrote() -> None:
    """End to end on the REAL cache dir: candidate name == the file on disk."""

    res = resolve_owlv2_provider(default_weights_dir(), available_execution_providers=CUDA_BOX)
    assert res.selected == PROVIDER_CUDA_FP16
    assert res.model_file == _OWLV2_FP16
    assert res.model_file.is_file()


# ---------------------------------------------------------------------------
# 4. a machine without CUDA behaves EXACTLY as it did before this card
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _OWLV2_FP16.is_file(), reason="owlv2 fp16 artifact not installed")
def test_installing_fp16_does_not_change_what_a_cuda_less_box_runs_owlv2() -> None:
    """The regression this card could plausibly cause, checked against real files."""

    res = resolve_owlv2_provider(default_weights_dir(), available_execution_providers=CPU_BOX)
    assert res.selected == PROVIDER_CPU_INT8
    assert res.model_file.name == _MODEL_ONNX_CANDIDATES[0]
    assert res.execution_providers == ("CPUExecutionProvider",)


@pytest.mark.skipif(
    not all(p.is_file() for p in _SIGLIP_FP16), reason="siglip2 fp16 artifacts not installed"
)
def test_installing_fp16_does_not_change_what_a_cuda_less_box_runs_siglip2() -> None:
    text = resolve_text_provider(SIGLIP2_DIR, available_execution_providers=CPU_BOX)
    vision = resolve_vision_provider(SIGLIP2_DIR, available_execution_providers=CPU_BOX)
    assert (text.selected, vision.selected) == (PROVIDER_CPU_INT8, PROVIDER_CPU_INT8)
    assert text.model_file.name == _TEXT_ONNX_CANDIDATES[0]
    assert vision.model_file.name == _VISION_ONNX_CANDIDATES[0]


# ---------------------------------------------------------------------------
# 5. the lie check, at the LOADER boundary
# ---------------------------------------------------------------------------


def _fp16_tree(tmp_path: Path) -> Path:
    """A weights dir that looks fully installed to `resolve_provider`."""

    (tmp_path / _MODEL_ONNX_FP16_CANDIDATES[0]).write_bytes(b"")
    (tmp_path / _MODEL_ONNX_CANDIDATES[0]).write_bytes(b"")
    (tmp_path / "tokenizer.json").write_text("{}")
    return tmp_path


def test_a_cuda_session_ort_ran_on_the_cpu_degrades_the_LOADER_to_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole point of the fail-closed check, exercised through the loader.

    The provider LIST is monkeypatched to a CUDA box (this is the lie ORT tells);
    construction then reports the CPU-only providers ORT really gave. The loader
    must return ``None`` — the same degrade as absent weights — never a detector
    that reports ``cuda_fp16`` while running fp16 ops on the CPU at 726 ms.
    """

    wd = _fp16_tree(tmp_path)
    monkeypatch.setenv(PROVIDER_ENV, PROVIDER_CUDA_FP16)
    monkeypatch.setattr(
        "parcel_robot.perception_providers._live_execution_providers", lambda: CUDA_BOX
    )
    reached: list[str] = []

    class SessionThatLies:
        def __init__(self, weights_dir, model_onnx, *, resolution=None, **kw) -> None:
            reached.append(resolution.selected)
            assert_provider_honoured(resolution, ("CPUExecutionProvider",), model="owlv2")

    monkeypatch.setattr(owlv2_onnx, "OwlV2Detector", SessionThatLies)

    detector = load_owlv2_detector(wd, require_env=False)

    assert reached == [PROVIDER_CUDA_FP16], "the loader never got as far as a session"
    assert detector is None, (
        "the loader handed back a detector whose session onnxruntime ran on the CPU "
        "while the resolution said cuda_fp16 — a silent 6x latency regression"
    )


def test_the_siglip2_loader_degrades_the_same_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / _TEXT_ONNX_FP16_CANDIDATES[0]).write_bytes(b"")
    (tmp_path / "tokenizer.json").write_text("{}")
    monkeypatch.setenv(PROVIDER_ENV, PROVIDER_CUDA_FP16)
    monkeypatch.setenv(siglip2_onnx.ONNX_ENABLE_ENV, "1")
    monkeypatch.setattr(
        "parcel_robot.perception_providers._live_execution_providers", lambda: CUDA_BOX
    )

    class EmbedderThatLies:
        def __init__(self, weights_dir, model_onnx, *, resolution=None, **kw) -> None:
            assert_provider_honoured(resolution, ("CPUExecutionProvider",), model="siglip2-text")

    monkeypatch.setattr(siglip2_onnx, "_OnnxSigLIP2Embedder", EmbedderThatLies)

    assert load_onnx_embedder(tmp_path) is None


def test_the_lie_check_is_what_makes_that_degrade_happen() -> None:
    """Names the single call the two cells above depend on, so a deletion is loud."""

    with pytest.raises(ProviderNotHonouredError):
        assert_provider_honoured(
            resolve_owlv2_provider(
                Path("/nonexistent"),
                requested=PROVIDER_CUDA_FP16,
                available_execution_providers=CUDA_BOX,
                file_exists=lambda p: p.name == _MODEL_ONNX_FP16_CANDIDATES[0],
            ),
            ("CPUExecutionProvider",),
            model="owlv2",
        )


# ---------------------------------------------------------------------------
# 6. what the installed runtime actually is, when there is one
# ---------------------------------------------------------------------------


def test_the_installed_onnxruntime_is_reported_not_assumed() -> None:
    """Not a gate on CUDA being present — CI has none. It pins that the module
    under test reads the LIVE build rather than a constant, which is the only
    reason the resolution table means anything on a real machine."""

    import parcel_robot.perception_providers as pp

    live = pp._live_execution_providers()
    assert isinstance(live, tuple)
    assert "CPUExecutionProvider" in live or live == (), (
        f"onnxruntime reports {live!r} — no CPU provider at all is not a shape this "
        "stack has ever seen; the fallback order has nothing to land on"
    )
