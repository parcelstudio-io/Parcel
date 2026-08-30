"""Freeze the SOS-1 post-fix maintenance surface without mutating prior evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FILES = (
    "research/20260829/stop-only-safety-1/DESIGN.md",
    "research/20260829/stop-only-safety-1/POST_EVIDENCE_MAINTENANCE_2.md",
    "research/20260829/stop-only-safety-1/POST_EVIDENCE_MAINTENANCE_3.md",
    "research/20260829/stop-only-safety-1/freeze.py",
    "research/20260829/stop-only-safety-1/freeze_maintenance.py",
    "research/20260829/stop-only-safety-1/run.py",
    "research/20260829/stop-only-safety-1/verify.py",
    "research/20260829/stop-only-safety-1/verify_maintenance_strict.py",
    "src/parcel_robot/bridge/stop_only_gateway.py",
    "src/parcel_robot/safety_supervisor.py",
    "gateway/credentials.py",
    "gateway/core.py",
    "gateway/seam/cli.py",
    "deploy/orin/services/parcel-gateway.service",
    "deploy/orin/services/parcel-runtime.service",
    "deploy/orin/services/parcel-safety.service",
    "pyproject.toml",
    "tests/test_stop_only_safety.py",
    "tests/test_gateway_socket_credentials.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite frozen manifest: {output}")
    payload = {
        "schema_version": 3,
        "study": "SOS-1-lifecycle-oracle-maintenance",
        "files": {name: _sha256(REPO / name) for name in FILES},
    }
    output.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
