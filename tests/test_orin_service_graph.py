"""Static contract for the not-yet-installed Orin systemd skeleton."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVICES = REPO / "deploy" / "orin" / "services"

FIXED_ENV = {
    "parcel-gateway.service": {
        "PARCEL_ARMED": "0",
        "PARCEL_ROLE": "gateway",
        "PARCEL_GATEWAY_SPORT": "vendor",
        "PARCEL_UNITREE_STATE_TOPIC": "rt/sportmodestate",
        "PARCEL_UNITREE_LOW_STATE_TOPIC": "rt/lowstate",
        "PARCEL_UNITREE_SUBSCRIBER_QUEUE_DEPTH": "0",
        "PARCEL_GATEWAY_SOCKET": "/run/parcel-gateway/gateway.sock",
        "PARCEL_GATEWAY_SOCKET_MODE": "0660",
        "PARCEL_GATEWAY_CLIENT_USER": "parcel-runtime",
        "PARCEL_GATEWAY_CLIENT_GROUP": "parcel-motion",
        "PARCEL_GATEWAY_STOP_CLIENT_USER": "parcel-safety",
    },
    "parcel-safety.service": {
        "PARCEL_ARMED": "0",
        "PARCEL_ROLE": "safety",
        "PARCEL_GATEWAY_SOCKET": "/run/parcel-gateway/gateway.sock",
    },
    "parcel-runtime.service": {
        "PARCEL_ARMED": "0",
        "PARCEL_ROLE": "runtime",
        "PARCEL_GATEWAY_SOCKET": "/run/parcel-gateway/gateway.sock",
    },
    "parcel-lio.service": {"PARCEL_ARMED": "0", "PARCEL_ROLE": "lio"},
    "parcel-audio.service": {
        "PARCEL_ARMED": "0",
        "PARCEL_ROLE": "audio",
        "PARCEL_VOICE_MODE": "push_to_talk",
    },
}


def _unit(name: str) -> str:
    return (SERVICES / name).read_text(encoding="utf-8")


def _exec_tokens(name: str) -> list[str]:
    line = next(line for line in _unit(name).splitlines() if line.startswith("ExecStart="))
    return shlex.split(line.removeprefix("ExecStart="))


def test_runtime_selects_the_reviewed_go2_overlay_exactly_once() -> None:
    runtime = _unit("parcel-runtime.service")

    assert "--profile go2_edu_plus" in runtime
    assert runtime.count("--profile go2_edu_plus") == 1
    assert "PARCEL_PROFILE=" not in runtime
    assert "--profile physical" not in runtime
    assert (REPO / "configs" / "robot.go2_edu_plus.yaml").is_file()


def test_target_orders_the_disarmed_fail_closed_stack() -> None:
    target = _unit("parcel.target")
    runtime = _unit("parcel-runtime.service")
    safety = _unit("parcel-safety.service")

    assert (
        "Requires=parcel-gateway.service parcel-safety.service "
        "parcel-runtime.service" in target
    )
    assert "Wants=parcel-lio.service parcel-audio.service" in target
    assert (
        "After=parcel-gateway.service parcel-safety.service parcel-lio.service "
        "parcel-audio.service parcel-runtime.service" in target
    )
    assert (
        "PropagatesStopTo=parcel-runtime.service parcel-audio.service "
        "parcel-lio.service parcel-gateway.service" in target
    )
    propagation = next(
        line for line in target.splitlines() if line.startswith("PropagatesStopTo=")
    )
    assert "parcel-safety.service" not in propagation
    assert "BindsTo=parcel-gateway.service parcel-safety.service" in runtime
    assert "Requires=parcel-gateway.service parcel-safety.service" in runtime
    assert "Wants=parcel-gateway.service" in safety
    assert "Requires=parcel-gateway.service" not in safety
    assert "BindsTo=parcel-gateway.service" not in safety
    assert "WantedBy=multi-user.target" in target
    assert "never grants motion authority" in target


def test_optional_environment_files_cannot_override_fixed_launch_invariants() -> None:
    for name, expected in FIXED_ENV.items():
        service = _unit(name)
        tokens = _exec_tokens(name)
        executable_index = next(
            index for index, token in enumerate(tokens) if token.startswith("/opt/parcel/bin/")
        )
        assignments = dict(token.split("=", 1) for token in tokens[1:executable_index])

        assert tokens[0] == "/usr/bin/env"
        assert assignments == expected
        assert "--disarmed" in tokens[executable_index + 1 :]
        assert "EnvironmentFile=-/etc/parcel/" in service
        assert service.index("EnvironmentFile=") < service.index("ExecStart=")
        assert not any(line.startswith("Environment=") for line in service.splitlines())

        inherited = os.environ.copy()
        inherited.update(dict.fromkeys(expected, "hostile-environment-file-value"))
        probe = subprocess.run(
            [
                "/usr/bin/env",
                *(f"{key}={value}" for key, value in assignments.items()),
                sys.executable,
                "-c",
                "import json, os, sys; print(json.dumps({k: os.environ[k] for k in sys.argv[1:]}))",
                *expected,
            ],
            check=True,
            capture_output=True,
            text=True,
            env=inherited,
        )
        assert json.loads(probe.stdout) == expected


def test_missing_service_artifacts_still_fail_loudly() -> None:
    readme = _unit("README.md")
    normalized_readme = " ".join(readme.split())
    for principal in ("runtime", "lio", "audio"):
        service = _unit(f"parcel-{principal}.service")
        executable = f"/opt/parcel/bin/parcel-{principal}"
        assert f"ExecStartPre=/usr/bin/test -x {executable}" in service
        assert f"`parcel-{principal}`" in readme or executable in readme
    assert "fail their own `ExecStartPre` loudly" in normalized_readme
    assert "fails loudly" in readme
