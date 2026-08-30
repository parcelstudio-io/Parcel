"""Run the frozen DMC-4 harness against the maintenance source manifest."""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_run_module():
    spec = importlib.util.spec_from_file_location("dmc4_frozen_runner", HERE / "run.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen DMC-4 runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = _load_run_module()
    module.SOURCE_MANIFEST_PATH = HERE / "maintenance_source_manifest_v2.json"
    result = module.main()
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
