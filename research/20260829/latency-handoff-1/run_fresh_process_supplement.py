"""Collect additive fresh-process provenance for the frozen LHO-1 study.

This launcher intentionally does not import the LHO simulator or verifier.  It
starts the already-frozen runner twice, in sequential child processes, and
records local Linux process provenance while each child is alive.  It refuses
to overwrite any retained supplement output.  A collection error aborts
without creating an evidence envelope; any partial child output remains in
place so the exclusive procedure cannot silently retry or claim a verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[2]
DEFAULT_VENV = REPOSITORY_ROOT / ".parcel"
DEFAULT_PYTHON = DEFAULT_VENV / "bin/python"
ORIGINAL_SOURCE_FILES = (
    "DESIGN.md",
    "AMENDMENT_1_COVERING_ARRAY.md",
    "AMENDMENT_2_PRE_EVIDENCE_AUDIT.md",
    "AMENDMENT_3_FREEZE_READINESS.md",
    "freeze_manifest.py",
    "freeze_sources.py",
    "run.py",
    "verify_results.py",
)
SUPPLEMENT_SOURCE_FILES = (
    "FRESH_PROCESS_SUPPLEMENT_PLAN.md",
    "run_fresh_process_supplement.py",
    "verify_fresh_process_supplement.py",
)
CHILD_ENV = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "TZ": "UTC",
}
COLLECTION_POLICY = {
    "child_timeout_s": 1800.0,
    "cleanup_grace_s": 5.0,
    "failure_envelope": False,
    "outputs_exclusive": True,
    "sequential_children": True,
}
EVIDENCE_TIER = (
    "local-host distinct-process reproducibility for the frozen deterministic "
    "scalar scheduling/kinematic simulation; no remote attestation or physical claim"
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _file_record(path: Path) -> dict[str, object]:
    supplied = _absolute(path)
    resolved = supplied.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"expected regular file: {supplied}")
    stat = resolved.stat()
    raw = resolved.read_bytes()
    return {
        "path": str(supplied),
        "resolved_path": str(resolved),
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256(raw),
    }


def _verify_self_digest(value: dict[str, object], label: str) -> None:
    expected = value.get("manifest_sha256")
    payload = dict(value)
    payload.pop("manifest_sha256", None)
    if expected != _sha256(_canonical(payload)):
        raise ValueError(f"{label} self-digest mismatch")


def _verify_original_source_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("original source manifest must be an object")
    if value.get("schema_version") != 1 or value.get("study") != "LHO-1":
        raise ValueError("unexpected original source-manifest identity")
    _verify_self_digest(value, "original source manifest")
    rows = value.get("files")
    if not isinstance(rows, dict) or set(rows) != set(ORIGINAL_SOURCE_FILES):
        raise ValueError("original source manifest inventory mismatch")
    for relative, expected in rows.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise TypeError("original source manifest row is malformed")
        if _sha256((ROOT / relative).read_bytes()) != expected:
            raise ValueError(f"original frozen source changed: {relative}")
    return value


def _verify_supplement_source_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("supplement source manifest must be an object")
    if value.get("schema_version") != 1:
        raise ValueError("unexpected supplement source-manifest schema")
    if value.get("study") != "LHO-1" or value.get("supplement") != "fresh-process":
        raise ValueError("unexpected supplement source-manifest identity")
    _verify_self_digest(value, "supplement source manifest")
    rows = value.get("files")
    if not isinstance(rows, dict) or set(rows) != set(SUPPLEMENT_SOURCE_FILES):
        raise ValueError("supplement source-manifest inventory mismatch")
    for relative, expected in rows.items():
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError(f"invalid supplement source digest: {relative}")
        if _sha256((ROOT / relative).read_bytes()) != expected:
            raise ValueError(f"supplement source changed after freeze: {relative}")
    return value


def _verify_original_manifest_shape(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("original manifest must be an object")
    _verify_self_digest(value, "original manifest")
    if value.get("schema_version") != 1 or value.get("study") != "LHO-1":
        raise ValueError("unexpected original manifest identity")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != 1980:
        raise ValueError("original manifest is not the full frozen case set")
    return value


def _binding_paths(
    *,
    python_path: Path,
    manifest_path: Path,
    source_manifest_path: Path,
    supplement_source_manifest_path: Path,
) -> dict[str, Path]:
    return {
        "design": ROOT / "DESIGN.md",
        "runner": ROOT / "run.py",
        "manifest": manifest_path,
        "source_manifest": source_manifest_path,
        "supplement_source_manifest": supplement_source_manifest_path,
        "supplement_plan": ROOT / "FRESH_PROCESS_SUPPLEMENT_PLAN.md",
        "supplement_launcher": ROOT / "run_fresh_process_supplement.py",
        "supplement_verifier": ROOT / "verify_fresh_process_supplement.py",
        "original_amendment_1": ROOT / "AMENDMENT_1_COVERING_ARRAY.md",
        "original_amendment_2": ROOT / "AMENDMENT_2_PRE_EVIDENCE_AUDIT.md",
        "original_amendment_3": ROOT / "AMENDMENT_3_FREEZE_READINESS.md",
        "original_freeze_manifest": ROOT / "freeze_manifest.py",
        "original_freeze_sources": ROOT / "freeze_sources.py",
        "original_verifier": ROOT / "verify_results.py",
        "python_executable": python_path,
        "retained_run_a": ROOT / "run_a.json",
        "retained_run_b": ROOT / "run_b.json",
        "retained_verification": ROOT / "verification.json",
    }


def _binding_snapshot(paths: dict[str, Path]) -> dict[str, dict[str, object]]:
    return {name: _file_record(path) for name, path in sorted(paths.items())}


def _read_boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    if not value:
        raise ValueError("Linux boot ID is unavailable")
    return value


def _read_proc_stat(pid: int) -> tuple[int, int]:
    raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    close = raw.rfind(")")
    if close < 0:
        raise ValueError("malformed /proc stat")
    fields = raw[close + 2 :].split()
    if len(fields) < 20:
        raise ValueError("truncated /proc stat")
    # The split tail starts at field 3 (state): PPID is field 4 and starttime
    # is field 22 in proc_pid_stat(5).
    return int(fields[1]), int(fields[19])


def _decode_cmdline(raw: bytes) -> list[str]:
    pieces = raw.split(b"\0")
    if pieces and pieces[-1] == b"":
        pieces.pop()
    if not pieces or any(piece == b"" for piece in pieces):
        raise ValueError("empty or malformed /proc command line")
    return [os.fsdecode(piece) for piece in pieces]


def _normalize_for_comparison(argv: list[str]) -> list[str]:
    normalized = list(argv)
    try:
        output_index = normalized.index("--output") + 1
    except (ValueError, IndexError) as exc:
        raise ValueError("child command has no output argument") from exc
    normalized[output_index] = "<OUTPUT>"
    return normalized


def _capture_live_process(
    child: subprocess.Popen[bytes],
    expected_argv: list[str],
    expected_python: dict[str, object],
) -> dict[str, object]:
    deadline = time.monotonic() + 5.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(
                "child exited before live /proc provenance could be captured"
            ) from last_error
        try:
            ppid, start_ticks = _read_proc_stat(child.pid)
            cmdline_raw = Path(f"/proc/{child.pid}/cmdline").read_bytes()
            proc_argv = _decode_cmdline(cmdline_raw)
            exe_path = Path(os.readlink(f"/proc/{child.pid}/exe"))
            proc_cwd = Path(os.readlink(f"/proc/{child.pid}/cwd")).resolve(strict=True)
            exe_record = _file_record(exe_path)
            if ppid != os.getpid():
                raise ValueError("child PPID does not identify this launcher")
            if proc_argv != expected_argv:
                raise ValueError("live /proc command line differs from spawn argv")
            if proc_cwd != ROOT:
                raise ValueError("live child working directory differs from the frozen root")
            if exe_record["resolved_path"] != expected_python["resolved_path"]:
                raise ValueError("live child executable path is not the frozen Python")
            if exe_record["sha256"] != expected_python["sha256"]:
                raise ValueError("live child executable digest is not the frozen Python")
            return {
                "captured_monotonic_ns": time.monotonic_ns(),
                "captured_utc": _utc_now(),
                "pid": child.pid,
                "ppid": ppid,
                "proc_start_ticks": start_ticks,
                "proc_cmdline_sha256": _sha256(cmdline_raw),
                "proc_cmdline_size": len(cmdline_raw),
                "proc_argv": proc_argv,
                "comparison_argv": _normalize_for_comparison(proc_argv),
                "proc_cwd": str(proc_cwd),
                "proc_executable": exe_record,
            }
        except (OSError, RuntimeError, ValueError) as exc:
            last_error = exc
            time.sleep(0.01)
    raise RuntimeError("unable to capture stable live child provenance") from last_error


def _output_record(
    path: Path,
    *,
    expected_manifest_digest: str,
    expected_source_digest: str,
) -> dict[str, object]:
    record = _file_record(path)
    value = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(value, dict):
        raise TypeError("child output is not an object")
    if value.get("schema_version") != 2 or value.get("study") != "LHO-1":
        raise ValueError("child output identity mismatch")
    metadata = value.get("run_metadata")
    if not isinstance(metadata, dict) or metadata.get("case_limit") is not None:
        raise ValueError("child output is not a full run")
    if value.get("manifest_sha256") != expected_manifest_digest:
        raise ValueError("child output manifest binding mismatch")
    if value.get("source_manifest_sha256") != expected_source_digest:
        raise ValueError("child output source binding mismatch")
    inventory = value.get("inventory")
    expected_inventory = {
        "paired_cases": 1980,
        "arm_episodes": 5940,
        "arms": ["B0", "F0", "G0"],
    }
    if inventory != expected_inventory:
        raise ValueError("child output inventory mismatch")
    aggregate = value.get("aggregate")
    if not isinstance(aggregate, dict):
        raise TypeError("child output aggregate is missing")
    digest = value.get("normalized_episode_digest")
    verdict = aggregate.get("preliminary_verdict")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("child normalized digest is missing")
    if not isinstance(verdict, str) or not verdict:
        raise ValueError("child preliminary verdict is missing")
    record.update(
        {
            "normalized_episode_digest": digest,
            "inventory": inventory,
            "preliminary_verdict": verdict,
            "run_metadata": metadata,
        }
    )
    return record


def _child_argv(
    *,
    python_path: Path,
    runner_path: Path,
    manifest_path: Path,
    source_manifest_path: Path,
    output_path: Path,
) -> list[str]:
    return [
        str(_absolute(python_path)),
        str(_absolute(runner_path)),
        "--manifest",
        str(_absolute(manifest_path)),
        "--source-manifest",
        str(_absolute(source_manifest_path)),
        "--output",
        str(_absolute(output_path)),
    ]


def _launch_one(
    *,
    label: str,
    boot_id: str,
    python_path: Path,
    python_record: dict[str, object],
    runner_path: Path,
    manifest_path: Path,
    source_manifest_path: Path,
    output_path: Path,
    manifest_digest: str,
    source_digest: str,
    child_env_digest: str,
) -> dict[str, object]:
    argv = _child_argv(
        python_path=python_path,
        runner_path=runner_path,
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        output_path=output_path,
    )
    parent_start_monotonic_ns = time.monotonic_ns()
    parent_start_utc = _utc_now()
    child = subprocess.Popen(
        argv,
        cwd=ROOT,
        env=CHILD_ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    popen_return_monotonic_ns = time.monotonic_ns()
    try:
        live = _capture_live_process(child, argv, python_record)
        stdout, stderr = child.communicate(timeout=COLLECTION_POLICY["child_timeout_s"])
    except subprocess.TimeoutExpired as exc:
        _terminate_and_reap(child)
        raise RuntimeError(
            f"{label} exceeded the {COLLECTION_POLICY['child_timeout_s']:.0f}s child timeout; "
            "collection aborted without an evidence envelope"
        ) from exc
    except BaseException:
        _terminate_and_reap(child)
        raise
    parent_end_monotonic_ns = time.monotonic_ns()
    parent_end_utc = _utc_now()
    record: dict[str, object] = {
        "label": label,
        "boot_id": boot_id,
        "launcher_pid": os.getpid(),
        "parent_start_monotonic_ns": parent_start_monotonic_ns,
        "popen_return_monotonic_ns": popen_return_monotonic_ns,
        "parent_end_monotonic_ns": parent_end_monotonic_ns,
        "parent_start_utc": parent_start_utc,
        "parent_end_utc": parent_end_utc,
        "spawn_argv": argv,
        "comparison_argv": _normalize_for_comparison(argv),
        "cwd": str(ROOT),
        "child_environment": dict(CHILD_ENV),
        "child_environment_sha256": child_env_digest,
        "exit_code": child.returncode,
        "stdout_size": len(stdout),
        "stdout_sha256": _sha256(stdout),
        "stderr_size": len(stderr),
        "stderr_sha256": _sha256(stderr),
        **live,
    }
    if child.returncode != 0:
        raise RuntimeError(
            f"{label} child exited {child.returncode}; stderr sha256={record['stderr_sha256']}"
        )
    record["output"] = _output_record(
        output_path,
        expected_manifest_digest=manifest_digest,
        expected_source_digest=source_digest,
    )
    return record


def _terminate_and_reap(child: subprocess.Popen[bytes]) -> None:
    """Boundedly stop and reap a child after collection failed."""

    if child.poll() is None:
        try:
            child.terminate()
        except ProcessLookupError:
            pass
    try:
        child.communicate(timeout=COLLECTION_POLICY["cleanup_grace_s"])
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate(timeout=COLLECTION_POLICY["cleanup_grace_s"])


def _require_exact_path(actual: Path, expected: Path, label: str) -> Path:
    actual_absolute = _absolute(actual)
    expected_absolute = _absolute(expected)
    if actual_absolute != expected_absolute:
        raise ValueError(f"{label} must be {expected_absolute}, got {actual_absolute}")
    return actual_absolute


def _write_exclusive(path: Path, value: dict[str, object]) -> None:
    payload = _canonical(value) + b"\n"
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch the two frozen LHO-1 fresh-process supplement runs."
    )
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    parser.add_argument("--source-manifest", type=Path, default=ROOT / "source-manifest.json")
    parser.add_argument(
        "--supplement-source-manifest",
        type=Path,
        default=ROOT / "fresh-process-source-manifest.json",
    )
    parser.add_argument("--run-c", type=Path, default=ROOT / "run_c.json")
    parser.add_argument("--run-d", type=Path, default=ROOT / "run_d.json")
    parser.add_argument("--evidence", type=Path, default=ROOT / "fresh-process-evidence.json")
    args = parser.parse_args()

    python_path = _require_exact_path(args.python, DEFAULT_PYTHON, "project Python")
    manifest_path = _require_exact_path(args.manifest, ROOT / "manifest.json", "manifest")
    source_manifest_path = _require_exact_path(
        args.source_manifest, ROOT / "source-manifest.json", "source manifest"
    )
    supplement_source_manifest_path = _require_exact_path(
        args.supplement_source_manifest,
        ROOT / "fresh-process-source-manifest.json",
        "supplement source manifest",
    )
    run_c_path = _require_exact_path(args.run_c, ROOT / "run_c.json", "run C")
    run_d_path = _require_exact_path(args.run_d, ROOT / "run_d.json", "run D")
    evidence_path = _require_exact_path(
        args.evidence, ROOT / "fresh-process-evidence.json", "evidence"
    )
    for path in (run_c_path, run_d_path, evidence_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite retained supplement file: {path}")

    launcher_start_monotonic_ns = time.monotonic_ns()
    launcher_start_utc = _utc_now()
    boot_id = _read_boot_id()
    python_record = _file_record(python_path)
    launcher_executable = _file_record(Path(sys.executable))
    if _absolute(Path(sys.executable)) != python_path:
        raise ValueError("launcher lexical sys.executable is not the frozen project Python")
    if _absolute(Path(sys.prefix)) != _absolute(DEFAULT_VENV):
        raise ValueError("launcher sys.prefix is not the frozen project virtual environment")
    if launcher_executable["resolved_path"] != python_record["resolved_path"]:
        raise ValueError("launcher itself must run under the frozen project Python")
    if launcher_executable["sha256"] != python_record["sha256"]:
        raise ValueError("launcher Python digest differs from frozen project Python")

    manifest = _verify_original_manifest_shape(manifest_path)
    source_manifest = _verify_original_source_manifest(source_manifest_path)
    supplement_source_manifest = _verify_supplement_source_manifest(supplement_source_manifest_path)
    binding_paths = _binding_paths(
        python_path=python_path,
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        supplement_source_manifest_path=supplement_source_manifest_path,
    )
    bindings_before_start_monotonic_ns = time.monotonic_ns()
    bindings_before_start_utc = _utc_now()
    bindings_before = _binding_snapshot(binding_paths)
    bindings_before_end_monotonic_ns = time.monotonic_ns()
    bindings_before_end_utc = _utc_now()
    child_env_digest = _sha256(_canonical(CHILD_ENV))
    toolchain = {
        "python": python_record,
        "launcher_python_version": platform.python_version(),
        "launcher_python_implementation": platform.python_implementation(),
        "launcher_sys_executable": str(_absolute(Path(sys.executable))),
        "launcher_sys_prefix": str(_absolute(Path(sys.prefix))),
        "launcher_base_prefix": str(_absolute(Path(sys.base_prefix))),
        "launcher_cache_tag": sys.implementation.cache_tag,
        "platform": sys.platform,
        "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
    }
    toolchain_digest = _sha256(_canonical(toolchain))

    run_c = _launch_one(
        label="C",
        boot_id=boot_id,
        python_path=python_path,
        python_record=python_record,
        runner_path=ROOT / "run.py",
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        output_path=run_c_path,
        manifest_digest=str(manifest["manifest_sha256"]),
        source_digest=str(source_manifest["manifest_sha256"]),
        child_env_digest=child_env_digest,
    )
    # This check is deliberately before D is spawned.  It is the procedural
    # barrier that makes the two child lifetimes sequential and non-overlapping.
    if run_c["exit_code"] != 0:
        raise RuntimeError("run C did not exit successfully; run D is forbidden")
    run_d = _launch_one(
        label="D",
        boot_id=boot_id,
        python_path=python_path,
        python_record=python_record,
        runner_path=ROOT / "run.py",
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        output_path=run_d_path,
        manifest_digest=str(manifest["manifest_sha256"]),
        source_digest=str(source_manifest["manifest_sha256"]),
        child_env_digest=child_env_digest,
    )
    bindings_after_start_monotonic_ns = time.monotonic_ns()
    bindings_after_start_utc = _utc_now()
    bindings_after = _binding_snapshot(binding_paths)
    bindings_after_end_monotonic_ns = time.monotonic_ns()
    bindings_after_end_utc = _utc_now()
    launcher_end_monotonic_ns = time.monotonic_ns()
    launcher_end_utc = _utc_now()

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "study": "LHO-1",
        "supplement": "fresh-process",
        "evidence_tier": EVIDENCE_TIER,
        "supplement_source_manifest_sha256": supplement_source_manifest["manifest_sha256"],
        "original_manifest_sha256": manifest["manifest_sha256"],
        "original_source_manifest_sha256": source_manifest["manifest_sha256"],
        "launcher": {
            "pid": os.getpid(),
            "boot_id": boot_id,
            "start_monotonic_ns": launcher_start_monotonic_ns,
            "end_monotonic_ns": launcher_end_monotonic_ns,
            "start_utc": launcher_start_utc,
            "end_utc": launcher_end_utc,
        },
        "child_environment": dict(CHILD_ENV),
        "child_environment_sha256": child_env_digest,
        "collection_policy": dict(COLLECTION_POLICY),
        "collection_policy_sha256": _sha256(_canonical(COLLECTION_POLICY)),
        "toolchain": toolchain,
        "toolchain_sha256": toolchain_digest,
        "bindings_before": bindings_before,
        "binding_observations": {
            "before_start_monotonic_ns": bindings_before_start_monotonic_ns,
            "before_end_monotonic_ns": bindings_before_end_monotonic_ns,
            "before_start_utc": bindings_before_start_utc,
            "before_end_utc": bindings_before_end_utc,
            "after_start_monotonic_ns": bindings_after_start_monotonic_ns,
            "after_end_monotonic_ns": bindings_after_end_monotonic_ns,
            "after_start_utc": bindings_after_start_utc,
            "after_end_utc": bindings_after_end_utc,
        },
        "launches": [run_c, run_d],
        "bindings_after": bindings_after,
        "bindings_stable": bindings_before == bindings_after,
        "does_not_prove": [
            "remote attestation or resistance to a malicious local evidence editor",
            "a learned policy or trainable Model A capability",
            "2-D/3-D route planning, perception, or social navigation competence",
            "quadruped dynamics, physical braking, Orin timing, or Go2 readiness",
        ],
    }
    evidence["evidence_sha256"] = _sha256(_canonical(evidence))
    _write_exclusive(evidence_path, evidence)
    if not evidence["bindings_stable"]:
        raise RuntimeError("frozen bindings changed during launch; evidence is retained as FAIL")
    print(
        json.dumps(
            {
                "status": "COLLECTED",
                "evidence": str(evidence_path),
                "evidence_sha256": evidence["evidence_sha256"],
                "run_c_pid": run_c["pid"],
                "run_d_pid": run_d["pid"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
