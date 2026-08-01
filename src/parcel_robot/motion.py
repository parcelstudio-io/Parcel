from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .models import VelocityCommand


class MotionBackend(Protocol):
    """Exclusive locomotion driver. Only one backend should command motion."""

    name: str

    def start(self, command: VelocityCommand) -> str: ...

    def stop(self) -> str: ...

    def status(self) -> str: ...


@dataclass
class SportMoveBackend:
    """Unitree SportClient high-level Move adapter.

    Uses ``unitree_sdk2py`` when installed and ``enabled`` is true. Otherwise it
    records commands so the voice/agent path can be developed offline.
    """

    interface: str = "lo"
    domain_id: int = 1
    enabled: bool = False
    name: str = "sport"
    history: list[VelocityCommand] = field(default_factory=list)
    _active: VelocityCommand | None = None
    _client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.go2.sport.sport_client import SportClient
        except ImportError as error:
            raise RuntimeError(
                "unitree_sdk2py is not installed; keep motion.backend=rl for "
                "local MuJoCo work, or install CycloneDDS + unitree_sdk2_python"
            ) from error
        ChannelFactoryInitialize(self.domain_id, self.interface)
        client = SportClient()
        client.SetTimeout(5.0)
        client.Init()
        self._client = client
        return client

    def start(self, command: VelocityCommand) -> str:
        self.history.append(command)
        self._active = command
        if not self.enabled:
            return (
                f"Sport Move armed (stub): vx={command.vx:.2f} "
                f"vy={command.vy:.2f} vyaw={command.vyaw:.2f}"
            )
        client = self._ensure_client()
        code = client.Move(float(command.vx), float(command.vy), float(command.vyaw))
        return f"Sport Move sent (code={code}): vx={command.vx:.2f}"

    def stop(self) -> str:
        self._active = VelocityCommand()
        if not self.enabled:
            return "Sport Move stopped (stub)"
        client = self._ensure_client()
        client.StopMove()
        return "Sport Move stopped"

    def status(self) -> str:
        if self._active is None:
            return "sport: idle"
        cmd = self._active
        mode = "live" if self.enabled else "stub"
        return f"sport[{mode}]: vx={cmd.vx:.2f} vy={cmd.vy:.2f} vyaw={cmd.vyaw:.2f}"


@dataclass
class RLPolicyBackend:
    """RL locomotion policy adapter.

    When ``policy_path`` points at a supported artifact, ``act()`` can be called
    from a control loop. Without a policy file the backend still accepts
    velocity commands so Parcel can route walk intents and forward them to
    ``parcel-sim``.
    """

    policy_path: str = ""
    control_dt: float = 0.02
    enabled: bool = True
    name: str = "rl"
    history: list[VelocityCommand] = field(default_factory=list)
    _active: VelocityCommand | None = None
    _policy: Any = None

    def __post_init__(self) -> None:
        path = Path(self.policy_path).expanduser() if self.policy_path else None
        if path and path.is_file():
            self._policy = self._load_policy(path)

    @staticmethod
    def _load_policy(path: Path) -> Any:
        suffix = path.suffix.lower()
        if suffix == ".onnx":
            try:
                import onnxruntime as ort
            except ImportError as error:
                raise RuntimeError(
                    "onnxruntime is required to load .onnx locomotion policies"
                ) from error
            return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        if suffix in {".pt", ".pth"}:
            try:
                import torch
            except ImportError as error:
                raise RuntimeError("torch is required to load .pt locomotion policies") from error
            policy = torch.jit.load(str(path), map_location="cpu")
            policy.eval()
            return policy
        raise RuntimeError(f"unsupported policy format: {path.suffix}")

    def start(self, command: VelocityCommand) -> str:
        self.history.append(command)
        self._active = command
        if self._policy is None:
            return (
                f"RL walk armed (no policy file): vx={command.vx:.2f} "
                f"vy={command.vy:.2f} vyaw={command.vyaw:.2f}"
            )
        return (
            f"RL walk armed with policy: vx={command.vx:.2f} "
            f"vy={command.vy:.2f} vyaw={command.vyaw:.2f}"
        )

    def stop(self) -> str:
        self._active = VelocityCommand()
        return "RL walk stopped"

    def status(self) -> str:
        policy = "loaded" if self._policy is not None else "stub"
        if self._active is None:
            return f"rl[{policy}]: idle"
        cmd = self._active
        return f"rl[{policy}]: vx={cmd.vx:.2f} vy={cmd.vy:.2f} vyaw={cmd.vyaw:.2f}"

    def active_command(self) -> VelocityCommand | None:
        return self._active

    def act(self, observation: Any) -> Any:
        """Run one policy step. Raises if no policy file is configured."""
        if self._policy is None:
            raise RuntimeError(
                "No RL policy loaded. Set motion.rl.policy_path to an ONNX or TorchScript file."
            )
        if hasattr(self._policy, "run"):
            # ONNX Runtime session
            inputs = {self._policy.get_inputs()[0].name: observation}
            return self._policy.run(None, inputs)[0]
        return self._policy(observation)


@dataclass
class MotionRouter:
    """Selects exactly one locomotion backend and exposes a stable API."""

    backends: dict[str, MotionBackend]
    active: str
    on_command: Callable[[VelocityCommand], None] | None = None
    on_stop: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        if self.active not in self.backends:
            raise ValueError(
                f"unknown motion backend {self.active!r}; "
                f"expected one of {sorted(self.backends)}"
            )

    @property
    def backend(self) -> MotionBackend:
        return self.backends[self.active]

    def set_backend(self, name: str) -> str:
        if name not in self.backends:
            raise ValueError(f"unknown motion backend: {name}")
        self.backend.stop()
        if self.on_stop is not None:
            self.on_stop()
        self.active = name
        return f"Motion backend set to {name}"

    def walk(self, command: VelocityCommand) -> str:
        message = self.backend.start(command)
        if self.on_command is not None:
            self.on_command(command)
        return message

    def stop(self) -> str:
        message = self.backend.stop()
        if self.on_stop is not None:
            self.on_stop()
        return message

    def status(self) -> str:
        return self.backend.status()


def build_motion_router(config: dict[str, Any], **hooks: Any) -> MotionRouter:
    sport_cfg = dict(config.get("sport", {}))
    rl_cfg = dict(config.get("rl", {}))
    backends: dict[str, MotionBackend] = {
        "sport": SportMoveBackend(
            interface=str(sport_cfg.get("interface", "lo")),
            domain_id=int(sport_cfg.get("domain_id", 1)),
            enabled=bool(sport_cfg.get("enabled", False)),
        ),
        "rl": RLPolicyBackend(
            policy_path=str(rl_cfg.get("policy_path", "")),
            control_dt=float(rl_cfg.get("control_dt", 0.02)),
            enabled=bool(rl_cfg.get("enabled", True)),
        ),
    }
    active = str(config.get("backend", "rl"))
    return MotionRouter(
        backends=backends,
        active=active,
        on_command=hooks.get("on_command"),
        on_stop=hooks.get("on_stop"),
    )
