"""Fail-closed, single-use transactions for paired V8 evaluation runs.

Atomic creation of the dedicated transaction directory is the durable point of
no return.  Once it exists, the corpus is consumed even when the evaluator is
killed before it can install ``claim.json``.  This module intentionally has no
stale-claim recovery or delete API.

Callers must first call :func:`preflight_v8_transaction`.  Preflight verifies
the exact manifest, creates and probes every output parent, rejects aliases and
symlinks, and freezes directory identities.  The returned object can then be
used either as a callback wrapper::

    prepared.run(lambda transaction: transaction.write_json_artifact("report", report))

or as a context manager::

    with prepared.claim() as transaction:
        transaction.write_json_artifact("report", report)

Both forms install exactly one immutable ``completed`` or ``aborted`` outcome
for exceptions that Python can observe.  An uncatchable process death can leave
only the transaction directory or a claim without an outcome;
:func:`inspect_v8_transaction` classifies either state as permanently
indeterminate and consumed.

Claims, outcomes, and JSON results use canonical strict JSON. A transaction
may also predeclare opaque binary results produced by a format-specific
exclusive writer. Both kinds must be read-only, are SHA-addressed at
completion, and are rehashed during every later inspection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any, Self, TypeVar

SCHEMA_VERSION = 1
_CLAIM_KIND = "parcel.v8.evaluation-claim"
_OUTCOME_KIND = "parcel.v8.evaluation-outcome"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_ARTIFACT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_STAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OWNERSHIP_NONCE = re.compile(r"^[0-9a-f]{64}$")
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_READ_CHUNK_BYTES = 1024 * 1024

T = TypeVar("T")


class V8TransactionError(RuntimeError):
    """Base error for an unsafe or inconsistent V8 transaction."""


class V8UnsafePathError(V8TransactionError):
    """Raised when a configured filesystem path is unsafe."""


class V8TransactionConsumedError(V8TransactionError):
    """Raised when any single-use transaction artifact already exists."""


class V8ArtifactExistsError(V8TransactionError, FileExistsError):
    """Raised when an immutable writer would replace an existing artifact."""


class V8TransactionState(str, Enum):
    """Durable state inferred solely from immutable transaction evidence."""

    AVAILABLE = "available"
    INDETERMINATE_HARD_ABORT = "indeterminate_hard_abort"
    COMPLETED = "completed"
    ABORTED = "aborted"
    INVALID = "invalid_consumed"


@dataclass(frozen=True, slots=True)
class V8EvaluationIdentity:
    """Exact run, corpus, and manifest identity installed in every record."""

    run_id: str
    corpus_id: str
    corpus_sha256: str
    manifest_id: str
    manifest_path: Path
    manifest_sha256: str

    def __post_init__(self) -> None:
        for name in ("run_id", "corpus_id", "manifest_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
                raise ValueError(f"{name} must be a path-safe identifier of at most 128 characters")
        for name in ("corpus_sha256", "manifest_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))


@dataclass(frozen=True, slots=True)
class V8TransactionPaths:
    """Every canonical path a transaction is permitted to create."""

    results_root: Path
    transaction_dir: Path
    claim_path: Path
    outcome_path: Path
    artifact_paths: Mapping[str, Path]
    binary_artifact_paths: Mapping[str, Path] = field(default_factory=dict)

    def __post_init__(self) -> None:
        artifacts: dict[str, Path] = {}
        binary_artifacts: dict[str, Path] = {}
        for raw_name, raw_path in self.artifact_paths.items():
            if not isinstance(raw_name, str) or not _SAFE_ARTIFACT_NAME.fullmatch(raw_name):
                raise ValueError(
                    "artifact names must start with a lowercase letter and contain only "
                    "lowercase letters, numbers, and underscores"
                )
            artifacts[raw_name] = Path(raw_path)
        for raw_name, raw_path in self.binary_artifact_paths.items():
            if not isinstance(raw_name, str) or not _SAFE_ARTIFACT_NAME.fullmatch(raw_name):
                raise ValueError(
                    "binary artifact names must start with a lowercase letter and contain only "
                    "lowercase letters, numbers, and underscores"
                )
            if raw_name in artifacts:
                raise ValueError(f"artifact name is declared twice: {raw_name}")
            binary_artifacts[raw_name] = Path(raw_path)
        if not artifacts and not binary_artifacts:
            raise ValueError("a V8 transaction must declare at least one result artifact")
        object.__setattr__(self, "results_root", Path(self.results_root))
        object.__setattr__(self, "transaction_dir", Path(self.transaction_dir))
        object.__setattr__(self, "claim_path", Path(self.claim_path))
        object.__setattr__(self, "outcome_path", Path(self.outcome_path))
        object.__setattr__(self, "artifact_paths", MappingProxyType(artifacts))
        object.__setattr__(
            self,
            "binary_artifact_paths",
            MappingProxyType(binary_artifacts),
        )


@dataclass(frozen=True, slots=True)
class V8ArtifactEvidence:
    """Content-addressed evidence for one canonical JSON artifact."""

    path: str
    sha256: str
    size_bytes: int
    canonical_json: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_json": self.canonical_json,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class V8TransactionInspection:
    """Read-only interpretation of a transaction's durable evidence."""

    state: V8TransactionState
    consumed: bool
    reason: str
    claim_sha256: str | None = None
    outcome_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class _NormalizedContract:
    root: Path
    transaction_dir: Path
    claim: Path
    outcome: Path
    artifacts: Mapping[str, Path]
    binary_artifact_names: frozenset[str]
    manifest: Path


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    device: int
    inode: int
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    path: Path
    device: int
    inode: int


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize strict JSON into one stable, newline-terminated byte form."""

    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    """Return the digest of :func:`canonical_json_bytes`."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _normalize_contract(
    identity: V8EvaluationIdentity,
    paths: V8TransactionPaths,
) -> _NormalizedContract:
    root = _absolute_lexical(paths.results_root)
    if root == Path(root.anchor):
        raise V8UnsafePathError("the filesystem root cannot be an evaluation results root")

    transaction_dir = _absolute_lexical(paths.transaction_dir)
    try:
        transaction_relative = transaction_dir.relative_to(root)
    except ValueError as exc:
        raise V8UnsafePathError(f"transaction_dir escapes results_root: {transaction_dir}") from exc
    if transaction_relative == Path("."):
        raise V8UnsafePathError("transaction_dir cannot be the results_root")

    claim = _absolute_lexical(paths.claim_path)
    outcome = _absolute_lexical(paths.outcome_path)
    json_artifacts = {
        name: _absolute_lexical(path) for name, path in sorted(paths.artifact_paths.items())
    }
    binary_artifacts = {
        name: _absolute_lexical(path) for name, path in sorted(paths.binary_artifact_paths.items())
    }
    artifacts = {**json_artifacts, **binary_artifacts}
    targets = {
        "single-use claim": claim,
        "terminal outcome": outcome,
        **{f"result artifact {name}": path for name, path in artifacts.items()},
    }
    for name, target in targets.items():
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise V8UnsafePathError(f"{name} path escapes results_root: {target}") from exc
        if relative == Path("."):
            raise V8UnsafePathError(f"{name} path cannot be the results_root")
    if len(set(targets.values())) != len(targets):
        raise V8UnsafePathError("claim, outcome, and result artifact paths must be distinct")
    for name, target in artifacts.items():
        if target == transaction_dir or target in transaction_dir.parents:
            raise V8UnsafePathError(
                f"artifact {name} cannot be the transaction_dir or one of its ancestors"
            )
        if transaction_dir in target.parents and target.parent != transaction_dir:
            raise V8UnsafePathError(
                f"artifact {name} may be a direct transaction_dir child, but cannot be nested"
            )
    target_values = tuple(targets.values())
    for index, left in enumerate(target_values):
        for right in target_values[index + 1 :]:
            if left in right.parents or right in left.parents:
                raise V8UnsafePathError("transaction output paths cannot contain one another")
    if claim.parent != transaction_dir or outcome.parent != transaction_dir:
        raise V8UnsafePathError(
            "claim_path and outcome_path must be direct children of transaction_dir"
        )
    return _NormalizedContract(
        root=root,
        transaction_dir=transaction_dir,
        claim=claim,
        outcome=outcome,
        artifacts=MappingProxyType(artifacts),
        binary_artifact_names=frozenset(binary_artifacts),
        manifest=_absolute_lexical(identity.manifest_path),
    )


def _path_components(path: Path) -> tuple[Path, ...]:
    if not path.is_absolute():  # pragma: no cover - all internal callers normalize first.
        raise V8UnsafePathError(f"path must be absolute: {path}")
    current = Path(path.anchor)
    components = [current]
    for part in path.parts[1:]:
        current /= part
        components.append(current)
    return tuple(components)


def _assert_no_symlink_components(path: Path, *, include_leaf: bool) -> None:
    components = _path_components(path)
    if not include_leaf:
        components = components[:-1]
    for component in components:
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode):
            raise V8UnsafePathError(f"symlink paths are forbidden: {component}")


def _ensure_directory_tree(directory: Path) -> None:
    for component in _path_components(directory):
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            try:
                os.mkdir(component, 0o755)
            except FileExistsError:
                metadata = os.lstat(component)
            else:
                metadata = os.lstat(component)
                _fsync_directory(component.parent)
        if stat.S_ISLNK(metadata.st_mode):
            raise V8UnsafePathError(f"symlink directories are forbidden: {component}")
        if not stat.S_ISDIR(metadata.st_mode):
            raise V8UnsafePathError(f"output parent is not a directory: {component}")


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform/filesystem dependent.
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:  # pragma: no cover - some filesystems reject directory fsync.
            pass
    finally:
        os.close(descriptor)


def _probe_directory(directory: Path) -> None:
    """Exercise create/write/fsync/unlink before the irreversible claim."""

    _assert_no_symlink_components(directory, include_leaf=True)
    probe = directory / f".parcel-v8-preflight-{os.getpid()}-{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(probe, flags, 0o600)
        created = True
        view = memoryview(b"parcel-v8-preflight\n")
        while view:
            written = os.write(descriptor, view)
            if written <= 0:  # pragma: no cover - defensive OS failure path.
                raise OSError("zero-byte write during output-directory preflight")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.unlink(probe)
            except FileNotFoundError:
                pass
    _fsync_directory(directory)


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _read_regular_file(path: Path, *, immutable: bool) -> tuple[bytes, os.stat_result]:
    _assert_no_symlink_components(path, include_leaf=True)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise V8UnsafePathError(f"cannot safely open regular file {path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise V8UnsafePathError(f"expected a regular file: {path}")
        if immutable and before.st_mode & _WRITE_BITS:
            raise V8UnsafePathError(f"immutable evidence is writable: {path}")
        if immutable and before.st_nlink != 1:
            raise V8UnsafePathError(f"immutable evidence has unexpected hard links: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, _READ_CHUNK_BYTES):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise V8UnsafePathError(f"file changed while it was read: {path}")
        raw = b"".join(chunks)
        if len(raw) != after.st_size:
            raise V8UnsafePathError(f"file size changed while it was read: {path}")
        return raw, after
    finally:
        os.close(descriptor)


def _snapshot_file(path: Path, *, immutable: bool) -> _FileSnapshot:
    raw, metadata = _read_regular_file(path, immutable=immutable)
    return _FileSnapshot(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _snapshot_directory(path: Path) -> _DirectorySnapshot:
    _assert_no_symlink_components(path, include_leaf=True)
    metadata = os.lstat(path)
    if not stat.S_ISDIR(metadata.st_mode):
        raise V8UnsafePathError(f"expected an output directory: {path}")
    return _DirectorySnapshot(path=path, device=metadata.st_dev, inode=metadata.st_ino)


def _parse_canonical_json(raw: bytes, path: Path) -> Mapping[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise V8TransactionError(f"invalid JSON evidence at {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise V8TransactionError(f"JSON evidence must be an object: {path}")
    if raw != canonical_json_bytes(value):
        raise V8TransactionError(f"JSON evidence is not in canonical form: {path}")
    return value


def _artifact_evidence(
    path: Path,
    *,
    canonical_json: bool,
) -> V8ArtifactEvidence:
    raw, _metadata = _read_regular_file(path, immutable=True)
    if canonical_json:
        _parse_canonical_json(raw, path)
    return V8ArtifactEvidence(
        path=str(path),
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        canonical_json=canonical_json,
    )


def _write_exclusive_json(path: Path, value: Any) -> V8ArtifactEvidence:
    encoded = canonical_json_bytes(value)
    _assert_no_symlink_components(path, include_leaf=False)
    if _lexists(path):
        raise V8ArtifactExistsError(f"refusing to replace immutable evidence: {path}")
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    temporary_created = False
    installed = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        temporary_created = True
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:  # pragma: no cover - defensive OS failure path.
                raise OSError("zero-byte write while creating immutable evidence")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise V8ArtifactExistsError(f"refusing to replace immutable evidence: {path}") from exc
        installed = True
        _fsync_directory(path.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_created:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        if installed:
            _fsync_directory(path.parent)
    return _artifact_evidence(path, canonical_json=True)


def _identity_payload(
    identity: V8EvaluationIdentity,
    contract: _NormalizedContract,
) -> dict[str, Any]:
    return {
        "corpus": {"id": identity.corpus_id, "sha256": identity.corpus_sha256},
        "manifest": {
            "id": identity.manifest_id,
            "path": str(contract.manifest),
            "sha256": identity.manifest_sha256,
        },
        "run_id": identity.run_id,
    }


def _paths_payload(contract: _NormalizedContract) -> dict[str, Any]:
    return {
        "artifacts": {name: str(path) for name, path in contract.artifacts.items()},
        "artifact_formats": {
            name: ("opaque_binary" if name in contract.binary_artifact_names else "canonical_json")
            for name in contract.artifacts
        },
        "claim": str(contract.claim),
        "outcome": str(contract.outcome),
        "results_root": str(contract.root),
        "transaction_dir": str(contract.transaction_dir),
    }


def _contract_sha256(
    identity: V8EvaluationIdentity,
    contract: _NormalizedContract,
) -> str:
    return canonical_json_sha256(
        {
            "identity": _identity_payload(identity, contract),
            "paths": _paths_payload(contract),
            "schema_version": SCHEMA_VERSION,
        }
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _exception_payload(error: BaseException) -> dict[str, str]:
    error_type = type(error)
    return {
        "class": f"{error_type.__module__}.{error_type.__qualname__}",
        "message": str(error)[:4096],
    }


def _claim_payload(
    identity: V8EvaluationIdentity,
    contract: _NormalizedContract,
    *,
    ownership_nonce: str,
) -> dict[str, Any]:
    return {
        "claimed_at_utc": _utc_timestamp(),
        "contract_sha256": _contract_sha256(identity, contract),
        "identity": _identity_payload(identity, contract),
        "kind": _CLAIM_KIND,
        "ownership_nonce": ownership_nonce,
        "paths": _paths_payload(contract),
        "schema_version": SCHEMA_VERSION,
    }


def _claim_matches(
    payload: Mapping[str, Any],
    identity: V8EvaluationIdentity,
    contract: _NormalizedContract,
) -> bool:
    expected_keys = {
        "claimed_at_utc",
        "contract_sha256",
        "identity",
        "kind",
        "ownership_nonce",
        "paths",
        "schema_version",
    }
    nonce = payload.get("ownership_nonce")
    return bool(
        set(payload) == expected_keys
        and payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("kind") == _CLAIM_KIND
        and payload.get("identity") == _identity_payload(identity, contract)
        and payload.get("paths") == _paths_payload(contract)
        and payload.get("contract_sha256") == _contract_sha256(identity, contract)
        and isinstance(nonce, str)
        and _OWNERSHIP_NONCE.fullmatch(nonce)
        and _valid_timestamp(payload.get("claimed_at_utc"))
    )


def _read_claim(
    identity: V8EvaluationIdentity,
    contract: _NormalizedContract,
) -> tuple[Mapping[str, Any], V8ArtifactEvidence]:
    raw, _metadata = _read_regular_file(contract.claim, immutable=True)
    payload = _parse_canonical_json(raw, contract.claim)
    if not _claim_matches(payload, identity, contract):
        raise V8TransactionError("the immutable claim does not match this transaction contract")
    return payload, V8ArtifactEvidence(
        path=str(contract.claim),
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )


def _directory_snapshots(
    contract: _NormalizedContract,
    *,
    include_transaction_dir: bool,
) -> tuple[_DirectorySnapshot, ...]:
    parents = {
        path.parent
        for path in contract.artifacts.values()
        if path.parent != contract.transaction_dir
    }
    parents.add(contract.transaction_dir.parent)
    parents.add(contract.root)
    if include_transaction_dir:
        parents.add(contract.transaction_dir)
    snapshots = tuple(_snapshot_directory(path) for path in sorted(parents, key=str))
    paths_by_identity: dict[tuple[int, int], Path] = {}
    for snapshot in snapshots:
        identity = (snapshot.device, snapshot.inode)
        aliased_path = paths_by_identity.setdefault(identity, snapshot.path)
        if aliased_path != snapshot.path:
            raise V8UnsafePathError(
                "distinct lexical output directories alias the same filesystem directory: "
                f"{aliased_path} and {snapshot.path}"
            )
    return snapshots


def _assert_directories_unchanged(snapshots: tuple[_DirectorySnapshot, ...]) -> None:
    for snapshot in snapshots:
        current = _snapshot_directory(snapshot.path)
        if (current.device, current.inode) != (snapshot.device, snapshot.inode):
            raise V8UnsafePathError(f"preflighted output directory was replaced: {snapshot.path}")


def _target_items(contract: _NormalizedContract) -> tuple[tuple[str, Path], ...]:
    return (
        ("terminal outcome", contract.outcome),
        ("single-use claim", contract.claim),
        *((f"result artifact {name}", path) for name, path in contract.artifacts.items()),
    )


class PreparedV8Transaction:
    """A path- and manifest-verified transaction that has not yet been claimed."""

    __slots__ = (
        "_contract",
        "_directories",
        "_manifest_snapshot",
        "_used",
        "identity",
        "paths",
    )

    def __init__(
        self,
        *,
        identity: V8EvaluationIdentity,
        paths: V8TransactionPaths,
        contract: _NormalizedContract,
        directories: tuple[_DirectorySnapshot, ...],
        manifest_snapshot: _FileSnapshot,
    ) -> None:
        self.identity = identity
        self.paths = paths
        self._contract = contract
        self._directories = directories
        self._manifest_snapshot = manifest_snapshot
        self._used = False

    def _revalidate(self) -> None:
        _assert_directories_unchanged(self._directories)
        current_manifest = _snapshot_file(self._contract.manifest, immutable=False)
        if current_manifest != self._manifest_snapshot:
            raise V8TransactionError("manifest identity changed after transaction preflight")
        _assert_no_symlink_components(self._contract.transaction_dir, include_leaf=True)
        if _lexists(self._contract.transaction_dir):
            raise V8TransactionConsumedError(
                "the dedicated transaction directory already exists; this corpus is consumed: "
                f"{self._contract.transaction_dir}"
            )
        for name, path in _target_items(self._contract):
            _assert_no_symlink_components(path, include_leaf=True)
            if _lexists(path):
                raise V8TransactionConsumedError(
                    f"{name} already exists; the transaction is not runnable: {path}"
                )

    def claim(self) -> ClaimedV8Transaction:
        """Install the irreversible, exclusive claim and return its context."""

        if self._used:
            raise V8TransactionConsumedError("this preflight object has already attempted a claim")
        self._used = True
        self._revalidate()
        ownership_nonce = secrets.token_hex(32)
        try:
            os.mkdir(self._contract.transaction_dir, 0o700)
        except FileExistsError as exc:
            raise V8TransactionConsumedError(
                "the dedicated transaction directory already exists; this corpus is consumed: "
                f"{self._contract.transaction_dir}"
            ) from exc
        _fsync_directory(self._contract.transaction_dir.parent)
        directories = _directory_snapshots(self._contract, include_transaction_dir=True)
        claim = _claim_payload(
            self.identity,
            self._contract,
            ownership_nonce=ownership_nonce,
        )
        expected_sha256 = canonical_json_sha256(claim)
        try:
            evidence = _write_exclusive_json(self._contract.claim, claim)
        except BaseException as error:
            try:
                installed, installed_evidence = _read_claim(self.identity, self._contract)
            except (OSError, V8TransactionError) as claim_read_error:
                raise error from claim_read_error
            if (
                installed.get("ownership_nonce") == ownership_nonce
                and installed_evidence.sha256 == expected_sha256
            ):
                claimed = ClaimedV8Transaction(
                    identity=self.identity,
                    paths=self.paths,
                    contract=self._contract,
                    directories=directories,
                    ownership_nonce=ownership_nonce,
                    claim_evidence=installed_evidence,
                )
                try:
                    claimed.abort(error, stage="single_use_claim_write")
                except BaseException as terminal_error:
                    raise terminal_error from error
            raise
        if evidence.sha256 != expected_sha256:
            error = V8TransactionError("installed claim digest differs from generated claim")
            claimed = ClaimedV8Transaction(
                identity=self.identity,
                paths=self.paths,
                contract=self._contract,
                directories=directories,
                ownership_nonce=ownership_nonce,
                claim_evidence=evidence,
            )
            try:
                claimed.abort(error, stage="single_use_claim_verification")
            except BaseException as terminal_error:
                raise terminal_error from error
            raise error
        return ClaimedV8Transaction(
            identity=self.identity,
            paths=self.paths,
            contract=self._contract,
            directories=directories,
            ownership_nonce=ownership_nonce,
            claim_evidence=evidence,
        )

    def run(self, callback: Callable[[ClaimedV8Transaction], T]) -> T:
        """Claim once, run ``callback``, and terminalize the transaction."""

        return self.claim().run(callback)


class ClaimedV8Transaction:
    """Callback/context API for one irrevocably consumed transaction."""

    __slots__ = (
        "_artifacts",
        "_claim_evidence",
        "_closed",
        "_contract",
        "_directories",
        "_ownership_nonce",
        "_stage",
        "identity",
        "paths",
    )

    def __init__(
        self,
        *,
        identity: V8EvaluationIdentity,
        paths: V8TransactionPaths,
        contract: _NormalizedContract,
        directories: tuple[_DirectorySnapshot, ...],
        ownership_nonce: str,
        claim_evidence: V8ArtifactEvidence,
    ) -> None:
        self.identity = identity
        self.paths = paths
        self._artifacts: dict[str, V8ArtifactEvidence] = {}
        self._contract = contract
        self._directories = directories
        self._ownership_nonce = ownership_nonce
        self._claim_evidence = claim_evidence
        self._stage = "claimed_execution"
        self._closed = False

    @property
    def claim_sha256(self) -> str:
        return self._claim_evidence.sha256

    @property
    def ownership_nonce(self) -> str:
        return self._ownership_nonce

    @property
    def stage(self) -> str:
        return self._stage

    def set_stage(self, stage: str) -> None:
        """Set a bounded diagnostic stage name for a potential abort outcome."""

        if self._closed:
            raise V8TransactionConsumedError("the transaction already has a terminal outcome")
        if not isinstance(stage, str) or not _SAFE_STAGE.fullmatch(stage):
            raise ValueError("stage must be a path-safe identifier of at most 128 characters")
        self._stage = stage

    def artifact_path(self, name: str) -> Path:
        """Return one declared canonical result path."""

        try:
            return self._contract.artifacts[name]
        except KeyError as exc:
            raise KeyError(f"undeclared V8 transaction artifact: {name}") from exc

    def write_json_artifact(self, name: str, value: Any) -> V8ArtifactEvidence:
        """Install a declared result as strict, canonical, no-clobber JSON."""

        if self._closed:
            raise V8TransactionConsumedError("the transaction already has a terminal outcome")
        path = self.artifact_path(name)
        if name in self._contract.binary_artifact_names:
            raise V8TransactionError(
                f"artifact {name} is declared opaque_binary, not canonical_json"
            )
        if name in self._artifacts:
            raise V8ArtifactExistsError(f"refusing to replace immutable evidence: {path}")
        _assert_directories_unchanged(self._directories)
        evidence = _write_exclusive_json(path, value)
        self._artifacts[name] = evidence
        return evidence

    def verify_binary_artifact(
        self,
        name: str,
        *,
        expected_sha256: str | None = None,
    ) -> V8ArtifactEvidence:
        """Authenticate one externally written immutable binary result.

        The path and binary format are frozen in the claim.  This method does
        not create or mutate the file; the format-specific writer must install
        it exclusively before calling this verifier.
        """

        if self._closed:
            raise V8TransactionConsumedError("the transaction already has a terminal outcome")
        path = self.artifact_path(name)
        if name not in self._contract.binary_artifact_names:
            raise V8TransactionError(
                f"artifact {name} is declared canonical_json, not opaque_binary"
            )
        if expected_sha256 is not None and _SHA256.fullmatch(expected_sha256) is None:
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
        _assert_directories_unchanged(self._directories)
        evidence = _artifact_evidence(path, canonical_json=False)
        if expected_sha256 is not None and evidence.sha256 != expected_sha256:
            raise V8TransactionError(f"binary artifact {name} does not match expected_sha256")
        registered = self._artifacts.get(name)
        if registered is not None:
            if evidence != registered:
                raise V8TransactionError(
                    f"binary artifact {name} changed after its first registration"
                )
            return evidence
        self._artifacts[name] = evidence
        return evidence

    def _collect_artifacts(self, *, require_all: bool) -> dict[str, dict[str, Any] | None]:
        if require_all and set(self._artifacts) != set(self._contract.artifacts):
            missing = sorted(set(self._contract.artifacts) - set(self._artifacts))
            if len(missing) == 1:
                raise V8TransactionError(
                    f"completed outcome requires result artifact {missing[0]} to be registered"
                )
            raise V8TransactionError(
                "completed outcome requires every result artifact to be registered; "
                f"missing: {', '.join(missing)}"
            )
        evidence: dict[str, dict[str, Any] | None] = {}
        for name, path in self._contract.artifacts.items():
            registered = self._artifacts.get(name)
            if registered is None:
                evidence[name] = None
                continue
            try:
                actual = _artifact_evidence(
                    path,
                    canonical_json=name not in self._contract.binary_artifact_names,
                )
            except (OSError, V8TransactionError):
                if require_all:
                    raise
                evidence[name] = None
                continue
            if actual != registered:
                if require_all:
                    raise V8TransactionError(
                        f"registered artifact {name} changed before transaction completion"
                    )
                evidence[name] = None
                continue
            evidence[name] = registered.as_dict()
        return evidence

    def _assert_claim_owned(self) -> None:
        claim, evidence = _read_claim(self.identity, self._contract)
        if (
            claim.get("ownership_nonce") != self._ownership_nonce
            or evidence != self._claim_evidence
        ):
            raise V8TransactionError("the installed claim is not owned by this transaction")

    def _write_outcome(
        self,
        *,
        status: str,
        stage: str,
        error: BaseException | None,
    ) -> V8ArtifactEvidence:
        if self._closed:
            raise V8TransactionConsumedError("the transaction already has a terminal outcome")
        if status not in {"completed", "aborted"}:
            raise ValueError(f"unsupported transaction outcome: {status}")
        if (status == "aborted") is (error is None):
            raise ValueError("aborted outcomes require an exception; completed outcomes forbid one")
        if not isinstance(stage, str) or not _SAFE_STAGE.fullmatch(stage):
            raise ValueError("stage must be a path-safe identifier of at most 128 characters")
        _assert_directories_unchanged(self._directories)
        self._assert_claim_owned()
        artifacts = self._collect_artifacts(require_all=status == "completed")
        outcome = {
            "artifacts": artifacts,
            "claim": self._claim_evidence.as_dict(),
            "contract_sha256": _contract_sha256(self.identity, self._contract),
            "exception": None if error is None else _exception_payload(error),
            "identity": _identity_payload(self.identity, self._contract),
            "kind": _OUTCOME_KIND,
            "ownership_nonce": self._ownership_nonce,
            "recorded_at_utc": _utc_timestamp(),
            "schema_version": SCHEMA_VERSION,
            "stage": stage,
            "status": status,
        }
        evidence = _write_exclusive_json(self._contract.outcome, outcome)
        self._closed = True
        return evidence

    def complete(self) -> V8ArtifactEvidence:
        """Install the completed outcome after every declared result exists."""

        return self._write_outcome(
            status="completed",
            stage="all_required_artifacts_written",
            error=None,
        )

    def abort(
        self,
        error: BaseException,
        *,
        stage: str | None = None,
    ) -> V8ArtifactEvidence:
        """Install the sole aborted outcome without removing the claim."""

        if not isinstance(error, BaseException):
            raise TypeError("abort requires a BaseException")
        return self._write_outcome(
            status="aborted",
            stage=stage or self._stage,
            error=error,
        )

    def run(self, callback: Callable[[ClaimedV8Transaction], T]) -> T:
        """Execute a callback and guarantee observable exceptions terminalize."""

        try:
            result = callback(self)
            self.complete()
        except BaseException as error:
            if not self._closed:
                try:
                    self.abort(error)
                except BaseException as terminal_error:
                    raise terminal_error from error
            raise
        return result

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        if error is not None:
            if not self._closed:
                try:
                    self.abort(error)
                except BaseException as terminal_error:
                    raise terminal_error from error
            return False
        if not self._closed:
            try:
                self.complete()
            except BaseException as completion_error:
                if not self._closed:
                    try:
                        self.abort(completion_error)
                    except BaseException as terminal_error:
                        raise terminal_error from completion_error
                raise
        return False


def preflight_v8_transaction(
    *,
    identity: V8EvaluationIdentity,
    paths: V8TransactionPaths,
) -> PreparedV8Transaction:
    """Verify all inputs and output directories before the irreversible claim."""

    contract = _normalize_contract(identity, paths)
    _assert_no_symlink_components(contract.manifest, include_leaf=True)
    manifest_snapshot = _snapshot_file(contract.manifest, immutable=False)
    if manifest_snapshot.sha256 != identity.manifest_sha256:
        raise V8TransactionError("manifest bytes do not match manifest_sha256")

    _assert_no_symlink_components(contract.transaction_dir, include_leaf=True)
    if _lexists(contract.transaction_dir):
        raise V8TransactionConsumedError(
            "the dedicated transaction directory already exists; this corpus is consumed: "
            f"{contract.transaction_dir}"
        )
    for _name, path in _target_items(contract):
        _assert_no_symlink_components(path, include_leaf=True)
        if _lexists(path):
            raise V8TransactionConsumedError(
                f"existing transaction evidence makes this corpus non-runnable: {path}"
            )

    parents = {contract.transaction_dir.parent}
    parents.update(
        path.parent
        for path in contract.artifacts.values()
        if path.parent != contract.transaction_dir
    )
    parents.add(contract.root)
    for parent in sorted(parents, key=lambda value: (len(value.parts), str(value))):
        _ensure_directory_tree(parent)
    for parent in sorted(parents, key=str):
        _probe_directory(parent)

    # The transaction directory is deliberately absent here: its atomic mkdir
    # in ``claim`` is the first irreversible, single-use operation.
    directories = _directory_snapshots(contract, include_transaction_dir=False)
    _assert_no_symlink_components(contract.transaction_dir, include_leaf=True)
    if _lexists(contract.transaction_dir):
        raise V8TransactionConsumedError(
            "transaction directory appeared during preflight; this corpus is consumed: "
            f"{contract.transaction_dir}"
        )
    for _name, path in _target_items(contract):
        _assert_no_symlink_components(path, include_leaf=True)
        if _lexists(path):
            raise V8TransactionConsumedError(
                f"transaction evidence appeared during preflight: {path}"
            )
    if _snapshot_file(contract.manifest, immutable=False) != manifest_snapshot:
        raise V8TransactionError("manifest identity changed during transaction preflight")
    return PreparedV8Transaction(
        identity=identity,
        paths=paths,
        contract=contract,
        directories=directories,
        manifest_snapshot=manifest_snapshot,
    )


def inspect_v8_transaction(
    *,
    identity: V8EvaluationIdentity,
    paths: V8TransactionPaths,
) -> V8TransactionInspection:
    """Inspect durable state without creating, deleting, or repairing anything."""

    try:
        contract = _normalize_contract(identity, paths)
        for path in (
            contract.root,
            contract.transaction_dir,
            contract.claim,
            contract.outcome,
            contract.manifest,
            *contract.artifacts.values(),
        ):
            _assert_no_symlink_components(path, include_leaf=True)
    except (OSError, V8TransactionError) as exc:
        return V8TransactionInspection(
            state=V8TransactionState.INVALID,
            consumed=True,
            reason=f"unsafe transaction path: {exc}",
        )

    transaction_dir_exists = _lexists(contract.transaction_dir)
    existing = {name: _lexists(path) for name, path in _target_items(contract)}
    if not transaction_dir_exists and not any(existing.values()):
        try:
            manifest = _snapshot_file(contract.manifest, immutable=False)
        except (OSError, V8TransactionError) as exc:
            return V8TransactionInspection(
                state=V8TransactionState.INVALID,
                consumed=True,
                reason=f"manifest cannot be authenticated: {exc}",
            )
        if manifest.sha256 != identity.manifest_sha256:
            return V8TransactionInspection(
                state=V8TransactionState.INVALID,
                consumed=True,
                reason="manifest bytes do not match the expected identity",
            )
        return V8TransactionInspection(
            state=V8TransactionState.AVAILABLE,
            consumed=False,
            reason="no transaction evidence exists",
        )

    if not transaction_dir_exists:
        return V8TransactionInspection(
            state=V8TransactionState.INVALID,
            consumed=True,
            reason="result or outcome evidence exists without its single-use claim",
        )
    try:
        transaction_metadata = os.lstat(contract.transaction_dir)
    except OSError as exc:
        return V8TransactionInspection(
            state=V8TransactionState.INVALID,
            consumed=True,
            reason=f"cannot inspect the transaction directory: {exc}",
        )
    if not stat.S_ISDIR(transaction_metadata.st_mode):
        return V8TransactionInspection(
            state=V8TransactionState.INVALID,
            consumed=True,
            reason="the dedicated transaction path exists but is not a directory",
        )
    if not _lexists(contract.claim):
        return V8TransactionInspection(
            state=V8TransactionState.INDETERMINATE_HARD_ABORT,
            consumed=True,
            reason=(
                "the dedicated transaction directory exists without its claim; "
                "this is an indeterminate_hard_abort and cannot be retried"
            ),
        )

    try:
        claim, claim_evidence = _read_claim(identity, contract)
    except (OSError, V8TransactionError) as exc:
        return V8TransactionInspection(
            state=V8TransactionState.INVALID,
            consumed=True,
            reason=f"claim evidence is invalid: {exc}",
        )

    if not _lexists(contract.outcome):
        return V8TransactionInspection(
            state=V8TransactionState.INDETERMINATE_HARD_ABORT,
            consumed=True,
            reason=(
                "a claim exists without a terminal outcome; the run is permanently "
                "indeterminate and cannot be retried"
            ),
            claim_sha256=claim_evidence.sha256,
        )

    try:
        outcome_raw, _metadata = _read_regular_file(contract.outcome, immutable=True)
        outcome = _parse_canonical_json(outcome_raw, contract.outcome)
        outcome_sha256 = hashlib.sha256(outcome_raw).hexdigest()
        expected_keys = {
            "artifacts",
            "claim",
            "contract_sha256",
            "exception",
            "identity",
            "kind",
            "ownership_nonce",
            "recorded_at_utc",
            "schema_version",
            "stage",
            "status",
        }
        if set(outcome) != expected_keys:
            raise V8TransactionError("terminal outcome fields do not match the schema")
        if (
            outcome.get("schema_version") != SCHEMA_VERSION
            or outcome.get("kind") != _OUTCOME_KIND
            or outcome.get("identity") != _identity_payload(identity, contract)
            or outcome.get("contract_sha256") != _contract_sha256(identity, contract)
            or outcome.get("ownership_nonce") != claim.get("ownership_nonce")
            or outcome.get("claim") != claim_evidence.as_dict()
            or not _valid_timestamp(outcome.get("recorded_at_utc"))
            or not isinstance(outcome.get("stage"), str)
            or not _SAFE_STAGE.fullmatch(str(outcome.get("stage")))
        ):
            raise V8TransactionError("terminal outcome does not match its claim and contract")
        raw_artifacts = outcome.get("artifacts")
        if not isinstance(raw_artifacts, Mapping) or set(raw_artifacts) != set(contract.artifacts):
            raise V8TransactionError("terminal outcome artifact membership changed")

        status_value = outcome.get("status")
        exception = outcome.get("exception")
        if status_value == "completed":
            if (
                outcome.get("stage") != "all_required_artifacts_written"
                or exception is not None
                or any(value is None for value in raw_artifacts.values())
            ):
                raise V8TransactionError("completed terminal outcome is incomplete")
            state = V8TransactionState.COMPLETED
        elif status_value == "aborted":
            if (
                not isinstance(exception, Mapping)
                or set(exception) != {"class", "message"}
                or not all(isinstance(value, str) for value in exception.values())
            ):
                raise V8TransactionError("aborted terminal outcome lacks exception evidence")
            state = V8TransactionState.ABORTED
        else:
            raise V8TransactionError("terminal outcome has an unsupported status")

        actual_artifacts: dict[str, dict[str, Any] | None] = {}
        for name, path in contract.artifacts.items():
            if raw_artifacts[name] is None:
                actual_artifacts[name] = None
                continue
            actual_artifacts[name] = _artifact_evidence(
                path,
                canonical_json=name not in contract.binary_artifact_names,
            ).as_dict()
        if dict(raw_artifacts) != actual_artifacts:
            raise V8TransactionError("terminal outcome artifact digests do not match disk")
    except (OSError, V8TransactionError) as exc:
        return V8TransactionInspection(
            state=V8TransactionState.INVALID,
            consumed=True,
            reason=f"terminal evidence is invalid: {exc}",
            claim_sha256=claim_evidence.sha256,
        )
    return V8TransactionInspection(
        state=state,
        consumed=True,
        reason=f"transaction has an immutable {state.value} outcome",
        claim_sha256=claim_evidence.sha256,
        outcome_sha256=outcome_sha256,
    )


__all__ = [
    "SCHEMA_VERSION",
    "ClaimedV8Transaction",
    "PreparedV8Transaction",
    "V8ArtifactEvidence",
    "V8ArtifactExistsError",
    "V8EvaluationIdentity",
    "V8TransactionConsumedError",
    "V8TransactionError",
    "V8TransactionInspection",
    "V8TransactionPaths",
    "V8TransactionState",
    "V8UnsafePathError",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "inspect_v8_transaction",
    "preflight_v8_transaction",
]
