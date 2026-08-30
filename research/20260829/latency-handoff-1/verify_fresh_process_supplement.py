"""Independently verify the additive LHO-1 fresh-process supplement.

The only project module imported here is the original frozen, standard-library
trace verifier.  This verifier does not import the runner, simulator, policy,
or any production robot module.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import sys
import zlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import verify_results as original

ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[2]
DEFAULT_VENV = REPOSITORY_ROOT / ".parcel"
DEFAULT_PYTHON = DEFAULT_VENV / "bin/python"
ORIGINAL_VERIFIER_PATH = ROOT / "verify_results.py"
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
FILE_FIELDS = (
    "path",
    "resolved_path",
    "device",
    "inode",
    "size",
    "mtime_ns",
    "sha256",
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


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _file_record(path: Path) -> dict[str, object]:
    supplied = _absolute(path)
    resolved = supplied.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"expected regular file: {supplied}")
    stat = resolved.stat()
    return {
        "path": str(supplied),
        "resolved_path": str(resolved),
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256(resolved.read_bytes()),
    }


def _base_file_record(record: object) -> dict[str, object]:
    if not isinstance(record, dict):
        raise TypeError("file record is not an object")
    try:
        return {key: record[key] for key in FILE_FIELDS}
    except KeyError as exc:
        raise ValueError(f"file record is missing {exc.args[0]}") from exc


def _verify_self_digest(value: dict[str, object], digest_key: str, label: str) -> None:
    expected = value.get(digest_key)
    payload = dict(value)
    payload.pop(digest_key, None)
    if expected != _sha256(_canonical(payload)):
        raise ValueError(f"{label} self-digest mismatch")


def _load_object(path: Path, encoding: str = "utf-8") -> dict[str, object]:
    value = json.loads(path.read_text(encoding=encoding))
    if not isinstance(value, dict):
        raise TypeError(f"JSON root is not an object: {path}")
    return value


def _verify_supplement_source_manifest(path: Path) -> dict[str, object]:
    value = _load_object(path)
    if value.get("schema_version") != 1:
        raise ValueError("unexpected supplement source-manifest schema")
    if value.get("study") != "LHO-1" or value.get("supplement") != "fresh-process":
        raise ValueError("unexpected supplement source-manifest identity")
    _verify_self_digest(value, "manifest_sha256", "supplement source manifest")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != set(SUPPLEMENT_SOURCE_FILES):
        raise ValueError("supplement source-manifest inventory mismatch")
    for relative, expected in files.items():
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError(f"invalid supplement source digest: {relative}")
        if _sha256((ROOT / relative).read_bytes()) != expected:
            raise ValueError(f"supplement source changed after freeze: {relative}")
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
        "original_verifier": ORIGINAL_VERIFIER_PATH,
        "python_executable": python_path,
        "retained_run_a": ROOT / "run_a.json",
        "retained_run_b": ROOT / "run_b.json",
        "retained_verification": ROOT / "verification.json",
    }


def _binding_snapshot(paths: dict[str, Path]) -> dict[str, dict[str, object]]:
    return {name: _file_record(path) for name, path in sorted(paths.items())}


def _child_argv(
    *,
    python_path: Path,
    manifest_path: Path,
    source_manifest_path: Path,
    output_path: Path,
) -> list[str]:
    return [
        str(_absolute(python_path)),
        str(ROOT / "run.py"),
        "--manifest",
        str(_absolute(manifest_path)),
        "--source-manifest",
        str(_absolute(source_manifest_path)),
        "--output",
        str(_absolute(output_path)),
    ]


def _comparison_argv(argv: list[str]) -> list[str]:
    value = list(argv)
    try:
        index = value.index("--output") + 1
    except (ValueError, IndexError) as exc:
        raise ValueError("child command has no output argument") from exc
    value[index] = "<OUTPUT>"
    return value


def _cmdline_bytes(argv: list[str]) -> bytes:
    if not argv or any(not isinstance(item, str) or "\0" in item for item in argv):
        raise ValueError("invalid recorded argv")
    return b"\0".join(os.fsencode(item) for item in argv) + b"\0"


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"invalid UTC timestamp: {label}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"invalid UTC timestamp: {label}") from exc
    return parsed


def _require_int(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"invalid integer: {label}")
    return value


def _require_exact_path(actual: Path, expected: Path, label: str) -> Path:
    actual_absolute = _absolute(actual)
    expected_absolute = _absolute(expected)
    if actual_absolute != expected_absolute:
        raise ValueError(f"{label} must be {expected_absolute}, got {actual_absolute}")
    return actual_absolute


def _verify_evidence_envelope(evidence: dict[str, object]) -> None:
    if evidence.get("schema_version") != 1:
        raise ValueError("unexpected evidence schema")
    if evidence.get("study") != "LHO-1" or evidence.get("supplement") != "fresh-process":
        raise ValueError("unexpected evidence identity")
    if evidence.get("evidence_tier") != EVIDENCE_TIER:
        raise ValueError("evidence-tier binding mismatch")
    _verify_self_digest(evidence, "evidence_sha256", "fresh-process evidence")


def _verify_original_verifier_import() -> None:
    imported = Path(str(original.__file__)).resolve(strict=True)
    if imported != ORIGINAL_VERIFIER_PATH.resolve(strict=True):
        raise ValueError(f"unexpected original verifier import: {imported}")


def _verify_launcher_and_toolchain(
    evidence: dict[str, object], expected_python: dict[str, object]
) -> None:
    launcher = evidence.get("launcher")
    if not isinstance(launcher, dict):
        raise TypeError("launcher metadata is missing")
    _require_int(launcher.get("pid"), "launcher pid", 1)
    start = _require_int(launcher.get("start_monotonic_ns"), "launcher start", 1)
    end = _require_int(launcher.get("end_monotonic_ns"), "launcher end", 1)
    if start >= end:
        raise ValueError("launcher monotonic chronology is invalid")
    if not isinstance(launcher.get("boot_id"), str) or not launcher["boot_id"]:
        raise ValueError("launcher boot ID is missing")
    if _parse_utc(launcher.get("start_utc"), "launcher start") >= _parse_utc(
        launcher.get("end_utc"), "launcher end"
    ):
        raise ValueError("launcher UTC chronology is invalid")

    if evidence.get("child_environment") != CHILD_ENV:
        raise ValueError("child environment is not the exact allowlist")
    env_digest = _sha256(_canonical(CHILD_ENV))
    if evidence.get("child_environment_sha256") != env_digest:
        raise ValueError("child environment digest mismatch")
    if evidence.get("collection_policy") != COLLECTION_POLICY:
        raise ValueError("collection policy binding mismatch")
    if evidence.get("collection_policy_sha256") != _sha256(_canonical(COLLECTION_POLICY)):
        raise ValueError("collection policy digest mismatch")

    toolchain = evidence.get("toolchain")
    if not isinstance(toolchain, dict):
        raise TypeError("toolchain metadata is missing")
    if evidence.get("toolchain_sha256") != _sha256(_canonical(toolchain)):
        raise ValueError("toolchain digest mismatch")
    if _base_file_record(toolchain.get("python")) != expected_python:
        raise ValueError("toolchain Python binding mismatch")
    if toolchain.get("launcher_python_version") != platform.python_version():
        raise ValueError("toolchain Python version differs from verifier runtime")
    if toolchain.get("launcher_python_implementation") != platform.python_implementation():
        raise ValueError("toolchain Python implementation mismatch")
    if toolchain.get("launcher_sys_executable") != str(_absolute(Path(sys.executable))):
        raise ValueError("toolchain lexical sys.executable mismatch")
    if toolchain.get("launcher_sys_prefix") != str(_absolute(Path(sys.prefix))):
        raise ValueError("toolchain sys.prefix mismatch")
    if toolchain.get("launcher_base_prefix") != str(_absolute(Path(sys.base_prefix))):
        raise ValueError("toolchain base_prefix mismatch")
    if toolchain.get("launcher_cache_tag") != sys.implementation.cache_tag:
        raise ValueError("toolchain cache tag mismatch")
    if toolchain.get("platform") != sys.platform:
        raise ValueError("toolchain platform mismatch")
    if toolchain.get("clock_ticks_per_second") != os.sysconf("SC_CLK_TCK"):
        raise ValueError("toolchain clock-tick rate mismatch")


def _verify_bindings(
    evidence: dict[str, object], expected_paths: dict[str, Path]
) -> dict[str, dict[str, object]]:
    before = evidence.get("bindings_before")
    after = evidence.get("bindings_after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise TypeError("pre/post binding snapshots are missing")
    if set(before) != set(expected_paths) or set(after) != set(expected_paths):
        raise ValueError("binding snapshot inventory mismatch")
    if evidence.get("bindings_stable") is not True or before != after:
        raise ValueError("frozen bindings changed between pre/post snapshots")
    live = _binding_snapshot(expected_paths)
    if after != live:
        raise ValueError("retained frozen bindings no longer match launcher snapshot")
    return live


def _launches(evidence: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    rows = evidence.get("launches")
    if (
        not isinstance(rows, list)
        or len(rows) != 2
        or not all(isinstance(row, dict) for row in rows)
    ):
        raise ValueError("evidence must contain exactly two launch records")
    run_c, run_d = rows
    if run_c.get("label") != "C" or run_d.get("label") != "D":
        raise ValueError("launch labels/order mismatch")
    return run_c, run_d


def _verify_launch_record(
    launch: dict[str, object],
    *,
    expected_argv: list[str],
    expected_python: dict[str, object],
    launcher: dict[str, object],
) -> None:
    launcher_pid = _require_int(launcher.get("pid"), "launcher pid", 1)
    if launch.get("launcher_pid") != launcher_pid or launch.get("ppid") != launcher_pid:
        raise ValueError("child parent identity mismatch")
    if launch.get("boot_id") != launcher.get("boot_id"):
        raise ValueError("child boot ID differs from launcher boot ID")
    _require_int(launch.get("pid"), "child pid", 1)
    _require_int(launch.get("proc_start_ticks"), "child start ticks", 1)
    parent_start = _require_int(launch.get("parent_start_monotonic_ns"), "child parent start", 1)
    popen_return = _require_int(launch.get("popen_return_monotonic_ns"), "child popen return", 1)
    captured = _require_int(launch.get("captured_monotonic_ns"), "child provenance capture", 1)
    parent_end = _require_int(launch.get("parent_end_monotonic_ns"), "child parent end", 1)
    if not (parent_start <= popen_return <= captured < parent_end):
        raise ValueError("child monotonic chronology is invalid")
    if not (
        int(launcher["start_monotonic_ns"])
        <= parent_start
        < parent_end
        <= int(launcher["end_monotonic_ns"])
    ):
        raise ValueError("child lifetime lies outside launcher lifetime")
    start_utc = _parse_utc(launch.get("parent_start_utc"), "child parent start")
    capture_utc = _parse_utc(launch.get("captured_utc"), "child capture")
    end_utc = _parse_utc(launch.get("parent_end_utc"), "child parent end")
    if not (start_utc <= capture_utc <= end_utc):
        raise ValueError("child UTC chronology is invalid")
    if launch.get("exit_code") != 0:
        raise ValueError("child exit code is nonzero")
    if launch.get("cwd") != str(ROOT):
        raise ValueError("child working directory mismatch")
    if launch.get("proc_cwd") != str(ROOT):
        raise ValueError("live /proc child working directory mismatch")
    if launch.get("child_environment") != CHILD_ENV:
        raise ValueError("launch child environment is not the exact allowlist")
    if launch.get("child_environment_sha256") != _sha256(_canonical(CHILD_ENV)):
        raise ValueError("launch child environment digest mismatch")
    if launch.get("spawn_argv") != expected_argv or launch.get("proc_argv") != expected_argv:
        raise ValueError("spawn/live argv differs from the expected frozen command")
    expected_comparison = _comparison_argv(expected_argv)
    if launch.get("comparison_argv") != expected_comparison:
        raise ValueError("spawn normalized argv mismatch")
    # The live capture overwrites the same key in the launcher record.  Requiring
    # the exact comparison value still proves that the captured /proc argv had
    # only the expected output-path variance.
    cmdline = _cmdline_bytes(expected_argv)
    if launch.get("proc_cmdline_size") != len(cmdline):
        raise ValueError("live /proc command-line size mismatch")
    if launch.get("proc_cmdline_sha256") != _sha256(cmdline):
        raise ValueError("live /proc command-line digest mismatch")
    proc_executable = _base_file_record(launch.get("proc_executable"))
    live_proc_executable = _file_record(Path(str(proc_executable["path"])))
    if proc_executable != live_proc_executable:
        raise ValueError("captured child executable no longer matches retained toolchain")
    if (
        proc_executable["resolved_path"] != expected_python["resolved_path"]
        or proc_executable["sha256"] != expected_python["sha256"]
    ):
        raise ValueError("child executable is not the frozen project Python")
    for key in ("stdout_size", "stderr_size"):
        _require_int(launch.get(key), key, 0)
    for key in ("stdout_sha256", "stderr_sha256"):
        value = launch.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"invalid {key}")


def _verify_process_identity_and_chronology(
    run_c: dict[str, object], run_d: dict[str, object]
) -> None:
    identity_c = (run_c.get("boot_id"), run_c.get("pid"), run_c.get("proc_start_ticks"))
    identity_d = (run_d.get("boot_id"), run_d.get("pid"), run_d.get("proc_start_ticks"))
    if identity_c == identity_d:
        raise ValueError("C/D process identities are duplicates")
    if run_c.get("boot_id") != run_d.get("boot_id"):
        raise ValueError("C/D were not observed in the same local boot")
    if run_c.get("pid") == run_d.get("pid"):
        raise ValueError("C/D child PIDs are not distinct")
    if int(run_c["proc_start_ticks"]) >= int(run_d["proc_start_ticks"]):
        raise ValueError("C/D kernel process start ticks are not strictly sequential")
    if int(run_c["parent_end_monotonic_ns"]) > int(run_d["parent_start_monotonic_ns"]):
        raise ValueError("C/D child lifetimes overlap")
    if _parse_utc(run_c.get("parent_end_utc"), "C end") > _parse_utc(
        run_d.get("parent_start_utc"), "D start"
    ):
        raise ValueError("C/D UTC chronology overlaps")
    if run_c.get("comparison_argv") != run_d.get("comparison_argv"):
        raise ValueError("C/D commands differ by more than output path")


def _verify_binding_observation_chronology(
    evidence: dict[str, object],
    run_c: dict[str, object],
    run_d: dict[str, object],
) -> None:
    launcher = evidence.get("launcher")
    observations = evidence.get("binding_observations")
    if not isinstance(launcher, dict) or not isinstance(observations, dict):
        raise TypeError("binding observation chronology is missing")
    before_start = _require_int(
        observations.get("before_start_monotonic_ns"), "pre-binding start", 1
    )
    before_end = _require_int(observations.get("before_end_monotonic_ns"), "pre-binding end", 1)
    after_start = _require_int(
        observations.get("after_start_monotonic_ns"), "post-binding start", 1
    )
    after_end = _require_int(observations.get("after_end_monotonic_ns"), "post-binding end", 1)
    if not (
        int(launcher["start_monotonic_ns"])
        <= before_start
        <= before_end
        <= int(run_c["parent_start_monotonic_ns"])
    ):
        raise ValueError("pre-run binding snapshot chronology is invalid")
    if not (
        int(run_d["parent_end_monotonic_ns"])
        <= after_start
        <= after_end
        <= int(launcher["end_monotonic_ns"])
    ):
        raise ValueError("post-run binding snapshot chronology is invalid")
    before_start_utc = _parse_utc(observations.get("before_start_utc"), "pre-binding start")
    before_end_utc = _parse_utc(observations.get("before_end_utc"), "pre-binding end")
    after_start_utc = _parse_utc(observations.get("after_start_utc"), "post-binding start")
    after_end_utc = _parse_utc(observations.get("after_end_utc"), "post-binding end")
    if not (
        _parse_utc(launcher.get("start_utc"), "launcher start")
        <= before_start_utc
        <= before_end_utc
        <= _parse_utc(run_c.get("parent_start_utc"), "C start")
    ):
        raise ValueError("pre-run binding UTC chronology is invalid")
    if not (
        _parse_utc(run_d.get("parent_end_utc"), "D end")
        <= after_start_utc
        <= after_end_utc
        <= _parse_utc(launcher.get("end_utc"), "launcher end")
    ):
        raise ValueError("post-run binding UTC chronology is invalid")


def _verify_output_record(launch: dict[str, object], expected_path: Path) -> dict[str, object]:
    record = launch.get("output")
    if not isinstance(record, dict):
        raise TypeError("launch output record is missing")
    if _base_file_record(record) != _file_record(expected_path):
        raise ValueError("retained output file identity/hash differs from live file")
    value = _load_object(expected_path, encoding="ascii")
    aggregate = value.get("aggregate")
    if not isinstance(aggregate, dict):
        raise TypeError("retained output aggregate is missing")
    metadata = value.get("run_metadata")
    if not isinstance(metadata, dict) or metadata.get("case_limit") is not None:
        raise ValueError("retained output is not a full run")
    if metadata.get("python") != platform.python_version():
        raise ValueError("retained output Python version differs from frozen toolchain")
    runtime_s = metadata.get("runtime_s")
    if isinstance(runtime_s, bool) or not isinstance(runtime_s, (int, float)) or runtime_s < 0:
        raise ValueError("retained output runtime metadata is invalid")
    if record.get("normalized_episode_digest") != value.get("normalized_episode_digest"):
        raise ValueError("retained output normalized digest mismatch")
    if record.get("inventory") != value.get("inventory"):
        raise ValueError("retained output inventory mismatch")
    if record.get("preliminary_verdict") != aggregate.get("preliminary_verdict"):
        raise ValueError("retained output preliminary verdict mismatch")
    if record.get("run_metadata") != metadata:
        raise ValueError("retained output run metadata mismatch")
    return value


def _verify_distinct_outputs(
    run_c: dict[str, object],
    run_d: dict[str, object],
    run_c_path: Path,
    run_d_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    value_c = _verify_output_record(run_c, run_c_path)
    value_d = _verify_output_record(run_d, run_d_path)
    record_c = run_c["output"]
    record_d = run_d["output"]
    if record_c["path"] == record_d["path"]:
        raise ValueError("C/D output paths are identical")
    if (record_c["device"], record_c["inode"]) == (
        record_d["device"],
        record_d["inode"],
    ):
        raise ValueError("C/D retained output inodes are identical")
    return value_c, value_d


def _validate_provenance_only(
    evidence: dict[str, object],
    *,
    python_path: Path,
    manifest_path: Path,
    source_manifest_path: Path,
    supplement_source_manifest_path: Path,
    run_c_path: Path,
    run_d_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    _verify_evidence_envelope(evidence)
    _verify_original_verifier_import()
    supplement_source = _verify_supplement_source_manifest(supplement_source_manifest_path)
    manifest = _load_object(manifest_path)
    original.verify_manifest(manifest)
    source = original._verify_source_manifest(source_manifest_path)
    if evidence.get("supplement_source_manifest_sha256") != supplement_source["manifest_sha256"]:
        raise ValueError("evidence supplement source-manifest binding mismatch")
    if evidence.get("original_manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("evidence original manifest binding mismatch")
    if evidence.get("original_source_manifest_sha256") != source["manifest_sha256"]:
        raise ValueError("evidence original source-manifest binding mismatch")
    expected_paths = _binding_paths(
        python_path=python_path,
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        supplement_source_manifest_path=supplement_source_manifest_path,
    )
    live_bindings = _verify_bindings(evidence, expected_paths)
    expected_python = live_bindings["python_executable"]
    _verify_launcher_and_toolchain(evidence, expected_python)
    launcher = evidence["launcher"]
    run_c, run_d = _launches(evidence)
    argv_c = _child_argv(
        python_path=python_path,
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        output_path=run_c_path,
    )
    argv_d = _child_argv(
        python_path=python_path,
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        output_path=run_d_path,
    )
    _verify_launch_record(
        run_c,
        expected_argv=argv_c,
        expected_python=expected_python,
        launcher=launcher,
    )
    _verify_launch_record(
        run_d,
        expected_argv=argv_d,
        expected_python=expected_python,
        launcher=launcher,
    )
    _verify_process_identity_and_chronology(run_c, run_d)
    _verify_binding_observation_chronology(evidence, run_c, run_d)
    return _verify_distinct_outputs(run_c, run_d, run_c_path, run_d_path)


def _restamp_evidence(evidence: dict[str, object]) -> None:
    evidence.pop("evidence_sha256", None)
    evidence["evidence_sha256"] = _sha256(_canonical(evidence))


def _tamper_checks(
    evidence: dict[str, object],
    provenance_validator: Callable[[dict[str, object]], object],
) -> dict[str, bool]:
    checks: dict[str, bool] = {}

    def rejected(name: str, mutate: Callable[[dict[str, object]], None]) -> None:
        altered = copy.deepcopy(evidence)
        mutate(altered)
        _restamp_evidence(altered)
        try:
            provenance_validator(altered)
        except (AssertionError, KeyError, OSError, TypeError, ValueError):
            checks[name] = True
        else:
            checks[name] = False

    def duplicate_identity(value: dict[str, object]) -> None:
        c, d = value["launches"]
        for key in ("boot_id", "pid", "proc_start_ticks"):
            d[key] = c[key]

    def duplicate_pid(value: dict[str, object]) -> None:
        c, d = value["launches"]
        d["pid"] = c["pid"]

    def duplicate_start_ticks(value: dict[str, object]) -> None:
        c, d = value["launches"]
        d["proc_start_ticks"] = c["proc_start_ticks"]

    def mutate_argv(value: dict[str, object]) -> None:
        launch = value["launches"][1]
        argv = list(launch["proc_argv"])
        argv[1] = str(ROOT / "not-the-frozen-runner.py")
        launch["proc_argv"] = argv
        launch["spawn_argv"] = list(argv)
        launch["comparison_argv"] = _comparison_argv(argv)
        raw = _cmdline_bytes(argv)
        launch["proc_cmdline_size"] = len(raw)
        launch["proc_cmdline_sha256"] = _sha256(raw)

    def mutate_source_hash(value: dict[str, object]) -> None:
        for snapshot in ("bindings_before", "bindings_after"):
            value[snapshot]["runner"]["sha256"] = "0" * 64

    def mutate_cwd(value: dict[str, object]) -> None:
        value["launches"][1]["proc_cwd"] = str(ROOT.parent)

    def overlap_chronology(value: dict[str, object]) -> None:
        c, d = value["launches"]
        d["parent_start_monotonic_ns"] = c["parent_end_monotonic_ns"] - 1

    def mutate_output_hash(value: dict[str, object]) -> None:
        value["launches"][1]["output"]["sha256"] = "0" * 64

    def duplicate_output_inode(value: dict[str, object]) -> None:
        c, d = value["launches"]
        d["output"]["device"] = c["output"]["device"]
        d["output"]["inode"] = c["output"]["inode"]

    def substitute_output(value: dict[str, object]) -> None:
        c, d = value["launches"]
        d["output"] = copy.deepcopy(c["output"])

    rejected("duplicate_process_identity", duplicate_identity)
    rejected("duplicate_child_pid", duplicate_pid)
    rejected("duplicate_process_start_ticks", duplicate_start_ticks)
    rejected("unexpected_argv", mutate_argv)
    rejected("unexpected_cwd", mutate_cwd)
    rejected("frozen_source_hash", mutate_source_hash)
    rejected("overlapping_chronology", overlap_chronology)
    rejected("output_hash", mutate_output_hash)
    rejected("duplicate_output_inode", duplicate_output_inode)
    rejected("output_substitution", substitute_output)
    return checks


def _gate(
    operation: Callable[[], dict[str, object]],
) -> dict[str, object]:
    try:
        details = operation()
    except (AssertionError, KeyError, OSError, TypeError, ValueError, zlib.error) as exc:
        return {"pass": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"pass": True, **details}


def _checked_summary(checked: dict[str, object]) -> dict[str, object]:
    aggregate = checked["aggregate"]
    return {
        "episodes_checked": checked["episodes_checked"],
        "normalized_episode_digest": checked["normalized_episode_digest"],
        "hypotheses": aggregate["hypotheses"],
        "preliminary_verdict": aggregate["preliminary_verdict"],
    }


def _write_exclusive(path: Path, value: dict[str, object]) -> None:
    payload = _canonical(value) + b"\n"
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify all eight LHO-1 fresh-process supplement gates."
    )
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    parser.add_argument("--source-manifest", type=Path, default=ROOT / "source-manifest.json")
    parser.add_argument(
        "--supplement-source-manifest",
        type=Path,
        default=ROOT / "fresh-process-source-manifest.json",
    )
    parser.add_argument("--evidence", type=Path, default=ROOT / "fresh-process-evidence.json")
    parser.add_argument("--run-a", type=Path, default=ROOT / "run_a.json")
    parser.add_argument("--run-b", type=Path, default=ROOT / "run_b.json")
    parser.add_argument("--run-c", type=Path, default=ROOT / "run_c.json")
    parser.add_argument("--run-d", type=Path, default=ROOT / "run_d.json")
    parser.add_argument("--output", type=Path, default=ROOT / "fresh-process-verification.json")
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
    evidence_path = _require_exact_path(
        args.evidence, ROOT / "fresh-process-evidence.json", "evidence"
    )
    run_a_path = _require_exact_path(args.run_a, ROOT / "run_a.json", "run A")
    run_b_path = _require_exact_path(args.run_b, ROOT / "run_b.json", "run B")
    run_c_path = _require_exact_path(args.run_c, ROOT / "run_c.json", "run C")
    run_d_path = _require_exact_path(args.run_d, ROOT / "run_d.json", "run D")
    output_path = _require_exact_path(
        args.output,
        ROOT / "fresh-process-verification.json",
        "verification output",
    )
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite retained verification: {output_path}")
    if _absolute(Path(sys.executable)) != python_path:
        raise ValueError("verifier lexical sys.executable is not the frozen project Python")
    if _absolute(Path(sys.prefix)) != _absolute(DEFAULT_VENV):
        raise ValueError("verifier sys.prefix is not the frozen project virtual environment")

    evidence = _load_object(evidence_path)
    _verify_original_verifier_import()
    supplement_source = _verify_supplement_source_manifest(supplement_source_manifest_path)
    manifest = _load_object(manifest_path)
    original.verify_manifest(manifest)
    source = original._verify_source_manifest(source_manifest_path)

    provenance_kwargs = {
        "python_path": python_path,
        "manifest_path": manifest_path,
        "source_manifest_path": source_manifest_path,
        "supplement_source_manifest_path": supplement_source_manifest_path,
        "run_c_path": run_c_path,
        "run_d_path": run_d_path,
    }

    def provenance(value: dict[str, object]) -> object:
        return _validate_provenance_only(value, **provenance_kwargs)

    run_c_launch, run_d_launch = _launches(evidence)
    cached_results: dict[str, Any] = {}

    def gate_1() -> dict[str, object]:
        _verify_evidence_envelope(evidence)
        if run_c_launch.get("exit_code") != 0 or run_d_launch.get("exit_code") != 0:
            raise ValueError("one or both child exit codes are nonzero")
        if not run_c_path.is_file() or not run_d_path.is_file():
            raise ValueError("one or both full retained outputs are missing")
        return {"child_exit_codes": [0, 0], "full_outputs_exist": True}

    def gate_2() -> dict[str, object]:
        _verify_process_identity_and_chronology(run_c_launch, run_d_launch)
        identities = [
            [row["boot_id"], row["pid"], row["proc_start_ticks"]]
            for row in (run_c_launch, run_d_launch)
        ]
        return {"distinct_process_identities": True, "identities": identities}

    def gate_3() -> dict[str, object]:
        _verify_evidence_envelope(evidence)
        expected_paths = _binding_paths(
            python_path=python_path,
            manifest_path=manifest_path,
            source_manifest_path=source_manifest_path,
            supplement_source_manifest_path=supplement_source_manifest_path,
        )
        live = _verify_bindings(evidence, expected_paths)
        _verify_launcher_and_toolchain(evidence, live["python_executable"])
        launcher = evidence["launcher"]
        _verify_launch_record(
            run_c_launch,
            expected_argv=_child_argv(
                python_path=python_path,
                manifest_path=manifest_path,
                source_manifest_path=source_manifest_path,
                output_path=run_c_path,
            ),
            expected_python=live["python_executable"],
            launcher=launcher,
        )
        _verify_launch_record(
            run_d_launch,
            expected_argv=_child_argv(
                python_path=python_path,
                manifest_path=manifest_path,
                source_manifest_path=source_manifest_path,
                output_path=run_d_path,
            ),
            expected_python=live["python_executable"],
            launcher=launcher,
        )
        _verify_process_identity_and_chronology(run_c_launch, run_d_launch)
        _verify_binding_observation_chronology(evidence, run_c_launch, run_d_launch)
        if (
            evidence.get("supplement_source_manifest_sha256")
            != supplement_source["manifest_sha256"]
        ):
            raise ValueError("supplement source-manifest binding mismatch")
        if evidence.get("original_manifest_sha256") != manifest["manifest_sha256"]:
            raise ValueError("original manifest binding mismatch")
        if evidence.get("original_source_manifest_sha256") != source["manifest_sha256"]:
            raise ValueError("original source-manifest binding mismatch")
        return {
            "sequential_nonoverlap": True,
            "expected_toolchain_and_command": True,
            "frozen_bindings_stable": True,
            "commands_differ_only_by_output": True,
        }

    def gate_4() -> dict[str, object]:
        value_c, value_d = _verify_distinct_outputs(
            run_c_launch, run_d_launch, run_c_path, run_d_path
        )
        cached_results["C"] = value_c
        cached_results["D"] = value_d
        return {
            "distinct_paths": True,
            "distinct_inodes": True,
            "retained_output_metadata_matches": True,
            "output_sha256": [
                run_c_launch["output"]["sha256"],
                run_d_launch["output"]["sha256"],
            ],
        }

    def gate_5() -> dict[str, object]:
        value_c = cached_results.get("C") or _load_object(run_c_path, encoding="ascii")
        value_d = cached_results.get("D") or _load_object(run_d_path, encoding="ascii")
        checked_c = original.verify_one(value_c, manifest, source)
        checked_d = original.verify_one(value_d, manifest, source)
        for label, checked in (("C", checked_c), ("D", checked_d)):
            hypotheses = checked["aggregate"]["hypotheses"]
            if not all(bool(row["pass"]) for row in hypotheses.values()):
                raise ValueError(f"run {label} does not pass original H1-H4")
        cached_results["checked_C"] = checked_c
        cached_results["checked_D"] = checked_d
        return {
            "original_trace_first_verifier": str(ORIGINAL_VERIFIER_PATH),
            "run_c": _checked_summary(checked_c),
            "run_d": _checked_summary(checked_d),
        }

    def gate_6() -> dict[str, object]:
        value_c = cached_results.get("C") or _load_object(run_c_path, encoding="ascii")
        value_d = cached_results.get("D") or _load_object(run_d_path, encoding="ascii")
        if value_c["normalized_episode_digest"] != value_d["normalized_episode_digest"]:
            raise ValueError("C/D normalized episode digests differ")
        if value_c["aggregate"] != value_d["aggregate"]:
            raise ValueError("C/D independently retained aggregates differ")
        return {
            "normalized_episode_digest": value_c["normalized_episode_digest"],
            "aggregates_identical": True,
        }

    def gate_7() -> dict[str, object]:
        value_a = _load_object(run_a_path, encoding="ascii")
        value_b = _load_object(run_b_path, encoding="ascii")
        value_c = cached_results.get("C") or _load_object(run_c_path, encoding="ascii")
        value_d = cached_results.get("D") or _load_object(run_d_path, encoding="ascii")
        checked_a = original.verify_one(value_a, manifest, source)
        checked_b = original.verify_one(value_b, manifest, source)
        digests = [
            checked_a["normalized_episode_digest"],
            checked_b["normalized_episode_digest"],
            value_c["normalized_episode_digest"],
            value_d["normalized_episode_digest"],
        ]
        aggregates = [
            checked_a["aggregate"],
            checked_b["aggregate"],
            value_c["aggregate"],
            value_d["aggregate"],
        ]
        if len(set(digests)) != 1:
            raise ValueError("A/B/C/D normalized episode digests do not match")
        if any(aggregate != aggregates[0] for aggregate in aggregates[1:]):
            raise ValueError("A/B/C/D aggregates do not match")
        return {
            "four_run_replication_link": True,
            "normalized_episode_digest": digests[0],
            "retained_a_b_raw_traces_reverified": True,
        }

    def gate_8() -> dict[str, object]:
        tamper = _tamper_checks(evidence, provenance)
        if not all(tamper.values()):
            raise ValueError(f"one or more deliberate tamper cases were accepted: {tamper}")
        return {"tamper_checks": tamper}

    gates = {
        "G1_exit_and_full_outputs": _gate(gate_1),
        "G2_distinct_process_identity": _gate(gate_2),
        "G3_chronology_command_and_frozen_bindings": _gate(gate_3),
        "G4_distinct_retained_output_identity": _gate(gate_4),
        "G5_original_trace_first_H1_H4": _gate(gate_5),
        "G6_c_d_normalized_replication": _gate(gate_6),
        "G7_a_b_c_d_replication_link": _gate(gate_7),
        "G8_deliberate_tamper_rejection": _gate(gate_8),
    }
    passed = all(bool(gate["pass"]) for gate in gates.values())
    output: dict[str, Any] = {
        "schema_version": 1,
        "study": "LHO-1",
        "supplement": "fresh-process",
        "integrity_status": "PASS" if passed else "FAIL",
        "gates": gates,
        "verdict": (
            "LHO1_MECHANISM_PASS_FRESH_PROCESS_SUPPLEMENTED"
            if passed
            else "LHO1_FRESH_PROCESS_EVIDENCE_REFUTED"
        ),
        "evidence_sha256": evidence.get("evidence_sha256"),
        "supplement_source_manifest_sha256": supplement_source["manifest_sha256"],
        "does_not_prove": [
            "remote attestation or resistance to a malicious local evidence editor",
            "a learned policy or trainable Model A capability",
            "2-D/3-D route planning, perception, or social navigation competence",
            "quadruped dynamics, physical braking, Orin timing, or Go2 readiness",
        ],
    }
    output["verification_sha256"] = _sha256(_canonical(output))
    _write_exclusive(output_path, output)
    print(
        json.dumps(
            {
                "status": output["integrity_status"],
                "verdict": output["verdict"],
                "verification_sha256": output["verification_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
