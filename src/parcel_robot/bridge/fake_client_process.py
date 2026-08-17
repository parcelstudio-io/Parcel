"""Hold a nonzero N24 fake-gateway proposal until a process test SIGKILLs us."""

from __future__ import annotations

import argparse
import json
import signal

from .client import FakeGatewayClientV1
from .protocol import GatewayAckDispositionV1, GatewayAckV1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--writer-id", default="n24-client")
    parser.add_argument("--vx-mps", type=float, default=0.2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    client = FakeGatewayClientV1.connect(args.socket)
    acquired = client.acquire(writer_id=args.writer_id)
    if not isinstance(acquired, GatewayAckV1) or (
        acquired.disposition is not GatewayAckDispositionV1.ACCEPTED
    ):
        raise RuntimeError(f"fake gateway acquire failed: {acquired}")
    admitted = client.command(
        writer_id=args.writer_id,
        sequence=2,
        vx_mps=args.vx_mps,
    )
    if not isinstance(admitted, GatewayAckV1) or (
        admitted.disposition is not GatewayAckDispositionV1.ACCEPTED
    ):
        raise RuntimeError(f"fake gateway command failed: {admitted}")
    print(
        json.dumps(
            {
                "event": "nonzero_admitted",
                "boot_epoch": client.hello.boot_epoch,
                "ack_scope": admitted.ack_scope,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    while True:
        signal.pause()


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
