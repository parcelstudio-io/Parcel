"""Run the frozen five-part tamper suite against maintained source hashes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    verifier = _load("dmc4_frozen_verifier_for_tamper", HERE / "verify_results.py")
    verifier.SOURCE_MANIFEST_PATH = HERE / "maintenance_source_manifest_v2.json"
    tamper = _load("dmc4_frozen_tamper", HERE / "tamper_check.py")
    tamper.SOURCE_MANIFEST_PATH = HERE / "maintenance_source_manifest_v2.json"
    tamper._load_verifier = lambda: verifier
    tamper.main()


if __name__ == "__main__":
    main()
