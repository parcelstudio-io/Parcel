"""Download and verify provenance-pinned reasoner challenger artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_LOCK = ROOT / "models.lock.json"


def load_lock(path: Path = DEFAULT_LOCK) -> dict[str, dict[str, Any]]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"unsupported model lock schema: {path}")
    models = payload.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError(f"model lock has no entries: {path}")
    for name, spec in models.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            raise TypeError("model lock entries must map IDs to objects")
        if not isinstance(spec.get("source_commit"), str) or len(spec["source_commit"]) != 40:
            raise ValueError(f"model {name!r} requires a 40-character source commit")
        if spec.get("license") != "Apache-2.0":
            raise ValueError(f"model {name!r} is not admitted by this Apache-only lock")
    return models


def sha256_file(path: Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(path: Path, spec: dict[str, Any]) -> None:
    if not path.is_file():
        raise ValueError(f"model artifact is not a regular file: {path}")
    expected_size = int(spec["size_bytes"])
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise ValueError(f"size mismatch for {path}: {actual_size} != {expected_size}")
    actual_digest = sha256_file(path)
    if actual_digest != spec["sha256"]:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual_digest}")


def fetch_model(name: str, spec: dict[str, Any], *, root: Path = ROOT) -> Path:
    relative = Path(str(spec["filename"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe model filename for {name!r}: {relative}")
    resolved_root = root.resolve()
    target = (resolved_root / relative).resolve()
    if resolved_root not in target.parents:
        raise ValueError(f"model path escapes cache for {name!r}: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        verify_model(target, spec)
        return target

    incomplete = target.with_name(f"{target.name}.incomplete")
    request = urllib.request.Request(
        str(spec["url"]),
        headers={"User-Agent": "Parcel-reasoner-model-fetch/1"},
    )
    # On failure the partial file stays visibly quarantined; it is never
    # exposed at the configured artifact path.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with urllib.request.urlopen(request, timeout=120) as response:
        descriptor = os.open(incomplete, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            while chunk := response.read(4 * 1024 * 1024):
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
    verify_model(incomplete, spec)
    os.replace(incomplete, target)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="*", help="model ids; default: all")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    locked = load_lock(args.lock)
    names = list(args.models) if args.models else list(locked)
    unknown = sorted(set(names) - set(locked))
    if unknown:
        parser.error(f"unknown model id(s): {', '.join(unknown)}")
    for name in names:
        path = fetch_model(name, locked[name], root=args.root)
        print(f"{name}\t{locked[name]['sha256']}\t{path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
