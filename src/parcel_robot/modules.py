from __future__ import annotations

from typing import Any, Protocol


class RobotModule(Protocol):
    """Contract for hardware or behavior extensions."""

    def commands(self) -> set[str]: ...

    def handle(self, command: str, argument: str) -> str | None: ...


class StatusModule:
    """Example module used as a template for custom modules."""

    def __init__(self, config: dict[str, Any]):
        self.label = str(config.get("label", "parcel-dog"))

    def commands(self) -> set[str]:
        return {"status"}

    def handle(self, command: str, argument: str) -> str | None:
        if command == "status":
            return f"{self.label} is ready"
        return None

