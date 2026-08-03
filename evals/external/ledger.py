"""Append-only provenance ledger for external evaluation runs.

Each run is stored twice:

* ``runs/<run-id>.json`` is the canonical, immutable record.
* ``runs.jsonl`` is an append-only index that is convenient for analysis.

The canonical record is installed with an atomic, no-clobber hard link.  The
index is appended under an advisory lock on platforms that provide ``fcntl``.
If a process fails between those operations, the canonical record remains
available and can be used to rebuild the index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised on POSIX; fallback is for Windows.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_DIR = Path(__file__).resolve().parent / "results" / "ledger"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMPONENT_NAMES = ("agent", "adapter", "config", "model")


class LedgerError(ValueError):
    """Raised when a run cannot be represented safely in the ledger."""


class DuplicateRunError(LedgerError):
    """Raised when a caller attempts to reuse an existing run identifier."""


@dataclass(frozen=True, slots=True)
class GitState:
    """Git provenance captured at evaluation time."""

    commit: str
    dirty: bool


@dataclass(frozen=True, slots=True)
class LedgerWriteResult:
    """Paths and record returned after a successful append."""

    record: dict[str, Any]
    record_path: Path
    index_path: Path


def sha256_file(path: str | Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of a file without loading it all into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def detect_git_state(repository: str | Path = REPOSITORY_ROOT) -> GitState:
    """Read the exact Parcel commit and whether tracked/untracked changes exist."""

    root = Path(repository).resolve()

    def run_git(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise LedgerError(f"cannot inspect Parcel Git state at {root}: {exc}") from exc
        return result.stdout.strip()

    commit = run_git("rev-parse", "HEAD")
    if not commit:
        raise LedgerError(f"Git returned an empty commit for {root}")
    status = run_git("status", "--porcelain=v1", "--untracked-files=normal")
    return GitState(commit=commit, dirty=bool(status))


def _required_text(value: str, field: str, *, max_length: int = 2048) -> str:
    normalized = value.strip()
    if not normalized:
        raise LedgerError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise LedgerError(f"{field} exceeds {max_length} characters")
    return normalized


def _json_object(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    """Validate and detach a mapping using strict, interoperable JSON."""

    try:
        encoded = json.dumps(value, allow_nan=False, sort_keys=True)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"{field} must be finite, JSON-serializable data: {exc}") from exc
    if not isinstance(decoded, dict):  # Defensive: callers are typed as Mapping.
        raise LedgerError(f"{field} must be a JSON object")
    return decoded


def _timestamp(now: datetime | None) -> tuple[datetime, str]:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise LedgerError("timestamp_utc must be timezone-aware")
    utc = value.astimezone(timezone.utc)
    return utc, utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _new_run_id(now: datetime) -> str:
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    return f"run-{stamp}-{uuid.uuid4().hex[:12]}"


def _component(identifier: str | None, digest: str | None) -> dict[str, str] | None:
    result: dict[str, str] = {}
    if identifier is not None:
        result["id"] = _required_text(identifier, "component identifier", max_length=1024)
    if digest is not None:
        result["hash"] = _required_text(digest, "component hash", max_length=1024)
    return result or None


def _fsync_directory(directory: Path) -> None:
    """Best-effort durability barrier for directory entry changes."""

    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform/filesystem dependent.
        return
    try:
        os.fsync(descriptor)
    except OSError:  # pragma: no cover - some filesystems reject directory fsync.
        pass
    finally:
        os.close(descriptor)


def _write_immutable_json(target: Path, payload: bytes) -> None:
    """Install a complete file atomically without ever replacing an old run."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise DuplicateRunError(f"evaluation run already exists: {target.stem}") from exc
        target.chmod(0o444)
        _fsync_directory(target.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_jsonl(index_path: Path, entry: Mapping[str, Any]) -> None:
    """Append one complete JSON line, serializing concurrent writers on POSIX."""

    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(entry, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(index_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:  # pragma: no cover - defensive OS failure path.
                raise OSError("zero-byte write while appending evaluation ledger")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    _fsync_directory(index_path.parent)


def record_evaluation_run(
    *,
    benchmark_id: str,
    benchmark_source: str,
    benchmark_source_commit: str,
    change_description: str,
    aggregate_metrics: Mapping[str, Any],
    report_path: str | Path,
    ledger_dir: str | Path = DEFAULT_LEDGER_DIR,
    parcel_repository: str | Path = REPOSITORY_ROOT,
    git_state: GitState | None = None,
    run_id: str | None = None,
    timestamp_utc: datetime | None = None,
    agent_id: str | None = None,
    agent_hash: str | None = None,
    adapter_id: str | None = None,
    adapter_hash: str | None = None,
    config_id: str | None = None,
    config_hash: str | None = None,
    model_id: str | None = None,
    model_hash: str | None = None,
) -> LedgerWriteResult:
    """Create one immutable evaluation record and append its index entry.

    ``git_state`` exists for importing externally orchestrated runs and for
    deterministic tests.  Normal callers should omit it so Parcel provenance is
    measured at write time.
    """

    utc_now, timestamp = _timestamp(timestamp_utc)
    identifier = run_id or _new_run_id(utc_now)
    if not _SAFE_RUN_ID.fullmatch(identifier):
        raise LedgerError(
            "run_id must contain only letters, numbers, '.', '_' or '-' and be at most 128 chars"
        )

    description = _required_text(change_description, "change_description")
    metrics = _json_object(aggregate_metrics, "aggregate_metrics")
    state = git_state or detect_git_state(parcel_repository)
    if not state.commit.strip():
        raise LedgerError("Parcel Git commit must not be empty")

    supplied_report = Path(report_path).expanduser()
    resolved_report = supplied_report.resolve()
    if not resolved_report.is_file():
        raise LedgerError(f"evaluation report does not exist or is not a file: {resolved_report}")

    raw_components = {
        "agent": _component(agent_id, agent_hash),
        "adapter": _component(adapter_id, adapter_hash),
        "config": _component(config_id, config_hash),
        "model": _component(model_id, model_hash),
    }
    components = {
        name: component
        for name, component in raw_components.items()
        if name in _COMPONENT_NAMES and component is not None
    }

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": identifier,
        "timestamp_utc": timestamp,
        "benchmark": {
            "id": _required_text(benchmark_id, "benchmark_id", max_length=1024),
            "source": _required_text(benchmark_source, "benchmark_source", max_length=2048),
            "source_commit": _required_text(
                benchmark_source_commit,
                "benchmark_source_commit",
                max_length=1024,
            ),
        },
        "parcel": {
            "git_commit": state.commit.strip(),
            "git_dirty": bool(state.dirty),
        },
        "components": components,
        "change_description": description,
        "aggregate_metrics": metrics,
        "report": {
            "path": str(resolved_report),
            "sha256": sha256_file(resolved_report),
            "size_bytes": resolved_report.stat().st_size,
        },
    }

    root = Path(ledger_dir).expanduser().resolve()
    record_path = root / "runs" / f"{identifier}.json"
    index_path = root / "runs.jsonl"
    encoded_record = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    _write_immutable_json(record_path, encoded_record)

    relative_record_path = record_path.relative_to(root)
    index_entry = dict(record)
    index_entry["record_path"] = relative_record_path.as_posix()
    _append_jsonl(index_path, index_entry)
    return LedgerWriteResult(record=record, record_path=record_path, index_path=index_path)


def iter_ledger(ledger_dir: str | Path = DEFAULT_LEDGER_DIR) -> Iterator[dict[str, Any]]:
    """Yield indexed evaluation records in append order."""

    index_path = Path(ledger_dir).expanduser().resolve() / "runs.jsonl"
    if not index_path.exists():
        return
    with index_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"invalid ledger JSON at {index_path}:{line_number}: {exc}") from exc
            if not isinstance(entry, dict):
                raise LedgerError(f"ledger entry at {index_path}:{line_number} is not an object")
            yield entry


def _load_report_metrics(report_path: Path, key: str) -> Mapping[str, Any]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read evaluation report {report_path}: {exc}") from exc
    if not isinstance(report, dict):
        raise LedgerError("evaluation report must be a JSON object")
    metrics = report.get(key)
    if not isinstance(metrics, dict):
        raise LedgerError(f"evaluation report key {key!r} must contain a JSON object")
    return metrics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and inspect external evaluation runs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="append one immutable evaluation run")
    record.add_argument("--benchmark-id", required=True)
    record.add_argument("--benchmark-source", required=True)
    record.add_argument("--benchmark-source-commit", required=True)
    record.add_argument("--description", required=True)
    record.add_argument("--report", type=Path, required=True)
    record.add_argument(
        "--metrics-json",
        help="aggregate metrics object; defaults to the report's aggregate key",
    )
    record.add_argument("--metrics-key", default="aggregate")
    record.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    record.add_argument("--parcel-repository", type=Path, default=REPOSITORY_ROOT)
    record.add_argument("--run-id")
    for name in _COMPONENT_NAMES:
        record.add_argument(f"--{name}-id")
        record.add_argument(f"--{name}-hash")

    listing = subparsers.add_parser("list", help="print indexed runs as a JSON array")
    listing.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    listing.add_argument("--limit", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            entries = list(iter_ledger(args.ledger_dir))
            if args.limit is not None:
                if args.limit < 0:
                    raise LedgerError("--limit must be non-negative")
                entries = entries[-args.limit :] if args.limit else []
            print(json.dumps(entries, indent=2, sort_keys=True))
            return 0

        if args.metrics_json is not None:
            decoded_metrics = json.loads(args.metrics_json)
            if not isinstance(decoded_metrics, dict):
                raise LedgerError("--metrics-json must contain a JSON object")
            metrics: Mapping[str, Any] = decoded_metrics
        else:
            metrics = _load_report_metrics(args.report, args.metrics_key)

        result = record_evaluation_run(
            benchmark_id=args.benchmark_id,
            benchmark_source=args.benchmark_source,
            benchmark_source_commit=args.benchmark_source_commit,
            change_description=args.description,
            aggregate_metrics=metrics,
            report_path=args.report,
            ledger_dir=args.ledger_dir,
            parcel_repository=args.parcel_repository,
            run_id=args.run_id,
            agent_id=args.agent_id,
            agent_hash=args.agent_hash,
            adapter_id=args.adapter_id,
            adapter_hash=args.adapter_hash,
            config_id=args.config_id,
            config_hash=args.config_hash,
            model_id=args.model_id,
            model_hash=args.model_hash,
        )
    except (LedgerError, json.JSONDecodeError, OSError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            {
                "run_id": result.record["run_id"],
                "record_path": str(result.record_path),
                "index_path": str(result.index_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
