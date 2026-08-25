"""The acoustic eval's process status and PipeWire graph must fail closed."""

import contextlib
import os
import subprocess
import threading
import time

import numpy as np
import pytest

from evals.companion.acoustic_loop_v1 import rig as rig_mod
from evals.companion.acoustic_loop_v1.rig import (
    AcousticRig,
    RigError,
    _matching_links,
    _owned_port_id,
    _Recorder,
    _temporary_binary_file,
)
from evals.companion.acoustic_loop_v1.run_acoustic_loop_v1 import quality_exit_code


class _FakeProcess:
    args = ("pw-record", "--target", "parcel_test_mic")

    def __init__(self, *, stubborn: bool = False) -> None:
        self.returncode: int | None = None
        self.stubborn = stubborn
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self.stubborn:
            self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode


class _PipeProcess(_FakeProcess):
    """Small selectable Popen stand-in for capture cancellation tests."""

    def __init__(self) -> None:
        super().__init__()
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)

    def terminate(self) -> None:
        super().terminate()
        if self.write_fd >= 0:
            os.close(self.write_fd)
            self.write_fd = -1

    def kill(self) -> None:
        super().kill()
        if self.write_fd >= 0:
            os.close(self.write_fd)
            self.write_fd = -1

    def exit(self, returncode: int) -> None:
        self.returncode = returncode
        if self.write_fd >= 0:
            os.close(self.write_fd)
            self.write_fd = -1


def test_green_complete_acoustic_report_exits_zero() -> None:
    assert quality_exit_code({"gates_passed": True, "teardown_clean": True}) == 0


def test_red_or_invalid_acoustic_report_exits_nonzero() -> None:
    assert quality_exit_code({"gates_passed": False, "teardown_clean": True}) == 1
    assert quality_exit_code({"gates_passed": True, "teardown_clean": False}) == 1
    assert quality_exit_code({}) == 1


def test_rig_close_terminates_and_reaps_tracked_capture_process() -> None:
    rig = AcousticRig(prefix="parcel_test")
    process = _FakeProcess()
    rig._track_process(process)  # type: ignore[arg-type]

    rig.close()

    assert process.terminated is True
    assert process.killed is False
    assert rig.live_child_processes() == []


def test_rig_close_kills_a_capture_process_that_ignores_terminate() -> None:
    rig = AcousticRig(prefix="parcel_test")
    process = _FakeProcess(stubborn=True)
    rig._track_process(process)  # type: ignore[arg-type]

    rig.close()

    assert process.terminated is True
    assert process.killed is True
    assert rig.live_child_processes() == []


def _node(node_id: int, name: str) -> dict:
    return {
        "id": node_id,
        "type": "PipeWire:Interface:Node",
        "info": {"props": {"node.name": name}},
    }


def _port(
    port_id: int,
    node_id: int,
    direction: str,
    *,
    monitor: bool = False,
    local_id: int = 0,
) -> dict:
    return {
        "id": port_id,
        "type": "PipeWire:Interface:Port",
        "info": {
            "props": {
                "node.id": node_id,
                "port.id": local_id,
                "port.direction": direction,
                "port.monitor": monitor,
            }
        },
    }


def test_owned_port_resolution_uses_exact_node_and_global_port_id() -> None:
    graph = [
        _node(115, "parcel_mic"),
        _node(215, "parcel_mic_extra"),
        _port(119, 115, "out", monitor=True, local_id=0),
        _port(219, 215, "out", monitor=True, local_id=0),
    ]

    assert _owned_port_id("parcel_mic", direction="out", monitor=True, graph=graph) == 119


def test_owned_port_resolution_refuses_missing_ambiguous_or_nonmonitor_ports() -> None:
    with pytest.raises(RigError, match="no out monitor port"):
        _owned_port_id(
            "parcel_mic",
            direction="out",
            monitor=True,
            graph=[_node(115, "parcel_mic"), _port(119, 115, "out")],
        )
    with pytest.raises(RigError, match="multiple PipeWire nodes"):
        _owned_port_id(
            "parcel_mic",
            direction="out",
            monitor=True,
            graph=[_node(115, "parcel_mic"), _node(116, "parcel_mic")],
        )
    with pytest.raises(RigError, match="multiple out monitor ports"):
        _owned_port_id(
            "parcel_mic",
            direction="out",
            monitor=True,
            graph=[
                _node(115, "parcel_mic"),
                _port(119, 115, "out", monitor=True),
                _port(120, 115, "out", monitor=True, local_id=1),
            ],
        )


def test_link_verification_uses_global_output_and_input_port_fields() -> None:
    graph = [
        {
            "id": 501,
            "type": "PipeWire:Interface:Link",
            "info": {"output-port-id": 119, "input-port-id": 116, "state": "active"},
        },
        {
            "id": 502,
            "type": "PipeWire:Interface:Link",
            "info": {"output-port-id": 999, "input-port-id": 116, "state": "active"},
        },
        {
            "id": 503,
            "type": "PipeWire:Interface:Link",
            "info": {"output-node-id": 119, "input-node-id": 116, "state": "active"},
        },
    ]

    assert [entry["id"] for entry in _matching_links(119, 116, graph=graph)] == [501]


def test_recorder_disables_autolinking_and_names_its_owned_mono_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    process = _PipeProcess()

    def fake_popen(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return process

    rig = AcousticRig(prefix="parcel_test")
    monkeypatch.setattr(rig_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        rig,
        "_await_owned_port_id",
        lambda name, **kwargs: 119 if name == "parcel_test_mic" else 116,
    )
    monkeypatch.setattr(rig, "_connect_ports", lambda output, input_: None)

    recorder = rig._start_recorder("parcel_test_mic", "-")
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[argv.index("--target") + 1] == "0"
    assert argv[argv.index("--channel-map") + 1] == "MONO"
    properties = argv[argv.index("--properties") + 1]
    assert "parcel_test_record_1" in properties
    rig._finish_recorder(recorder)


def _patch_pipe_recorder(
    monkeypatch: pytest.MonkeyPatch,
    rig: AcousticRig,
    process: _PipeProcess,
    *,
    stderr: bytes = b"",
) -> None:
    cleanup = contextlib.ExitStack()
    stderr_file = cleanup.enter_context(_temporary_binary_file())
    stderr_file.write(stderr)
    stderr_file.flush()
    recorder = _Recorder(
        process=process,  # type: ignore[arg-type]
        node_name="parcel_test_record_1",
        source_port_id=119,
        input_port_id=116,
        stderr_file=stderr_file,
        cleanup=cleanup,
    )
    monkeypatch.setattr(rig, "_start_recorder", lambda target, destination: recorder)
    monkeypatch.setattr(rig, "_disconnect_ports", lambda output, input_: None)


def test_capture_without_data_observes_stop_and_reaps_quickly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = AcousticRig(prefix="parcel_test")
    process = _PipeProcess()
    _patch_pipe_recorder(monkeypatch, rig, process)
    stop = threading.Event()
    timer = threading.Timer(0.1, stop.set)
    timer.start()
    started = time.monotonic()
    try:
        assert list(rig.capture_frames(stop=stop, first_frame_timeout_s=2.0)) == []
    finally:
        timer.cancel()

    assert time.monotonic() - started < 0.5
    assert process.terminated is True
    assert process.poll() is not None


def test_capture_accumulates_partial_reads_into_one_exact_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = AcousticRig(prefix="parcel_test")
    process = _PipeProcess()
    _patch_pipe_recorder(monkeypatch, rig, process)
    expected = np.arange(480, dtype=np.int16)
    payload = expected.tobytes()

    def write_parts() -> None:
        os.write(process.write_fd, payload[:301])
        time.sleep(0.05)
        os.write(process.write_fd, payload[301:])

    writer = threading.Thread(target=write_parts)
    writer.start()
    source = rig.capture_frames(first_frame_timeout_s=1.0)
    try:
        actual = next(source)
        assert np.array_equal(actual, expected)
    finally:
        source.close()
        writer.join(timeout=1.0)


def test_capture_reports_early_recorder_exit_with_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = AcousticRig(prefix="parcel_test")
    process = _PipeProcess()
    _patch_pipe_recorder(monkeypatch, rig, process, stderr=b"no route to source\n")
    process.exit(7)

    with pytest.raises(RigError, match="exited with 7.*no route to source"):
        list(rig.capture_frames(first_frame_timeout_s=1.0))


def test_concurrent_process_stop_is_idempotent() -> None:
    rig = AcousticRig(prefix="parcel_test")
    process = _FakeProcess()
    rig._track_process(process)  # type: ignore[arg-type]
    errors: list[Exception] = []

    def stop() -> None:
        try:
            rig._stop_process(process)  # type: ignore[arg-type]
        except (OSError, subprocess.SubprocessError, RigError) as error:
            errors.append(error)

    threads = [threading.Thread(target=stop) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1.0)

    assert errors == []
    assert process.poll() is not None
    assert rig.live_child_processes() == []
