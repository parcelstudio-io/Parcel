"""Clean-install ownership checks for the product-side gateway client."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"


def test_product_wheel_discovers_the_gateway_client_package() -> None:
    packaging = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert '[tool.setuptools.packages.find]\nwhere = ["src"]' in packaging
    assert (SRC / "parcel_robot" / "bridge" / "__init__.py").is_file()
    assert (SRC / "parcel_robot" / "bridge" / "gateway_client.py").is_file()


def test_product_gateway_adapter_imports_without_the_gateway_checkout_package() -> None:
    """Simulate the product wheel's import graph with the repository root absent."""

    probe = f"""
import sys
repo = {str(REPO)!r}
src = {str(SRC)!r}
sys.path[:] = [src] + [item for item in sys.path if item and repo not in item]
import parcel_robot.control.motion_gateway as adapter
assert adapter.MotionGatewayClientV1.__module__ == 'parcel_robot.bridge.gateway_client'
assert not any(name == 'gateway' or name.startswith('gateway.') for name in sys.modules)
print(adapter.MotionGatewayClientV1.__module__)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd="/",
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert result.stdout.strip() == "parcel_robot.bridge.gateway_client"
