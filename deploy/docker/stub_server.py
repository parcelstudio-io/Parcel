"""Minimal long-running stub for non-authority compose services."""

from __future__ import annotations

import os
import signal
import time


def main() -> int:
    name = os.environ.get("PARCEL_STUB_NAME", "stub")
    stop = {"flag": False}

    def _stop(_signum: int, _frame: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    print(f"parcel.{name}_stub ready (no authority; layout only)", flush=True)
    while not stop["flag"]:
        time.sleep(1.0)
    print(f"parcel.{name}_stub shutdown", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
