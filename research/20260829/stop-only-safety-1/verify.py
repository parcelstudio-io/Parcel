"""Independent stdlib verifier for two SOS-1 result files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("result must be a mapping")
    return value


def _verify_one(value: dict[str, object], manifest_sha: str) -> dict[str, object]:
    body = {key: item for key, item in value.items() if key != "run_label"}
    claimed_digest = body.pop("normalized_digest", None)
    digest_ok = claimed_digest == _sha256(_canonical(body))
    trials = body["trials"]
    gates = body["gates"]
    assert isinstance(trials, dict) and isinstance(gates, dict)
    h1 = all(
        trials[key] == 256
        for key in (
            "stop_uid_acquire_refused",
            "stop_uid_command_refused",
            "runtime_acquire_admitted",
            "runtime_command_admitted",
        )
    )
    h2 = all(
        trials[key] == 256
        for key in (
            "safety_stop_reached",
            "latched",
            "lease_invalidated",
            "exact_zero",
            "stationary_confirmed",
        )
    )
    api = body["api"]
    composition = body["composition"]
    lifecycle = body["lifecycle"]
    assert isinstance(api, dict) and isinstance(composition, dict) and isinstance(lifecycle, dict)
    h3 = api["pass"] is True and not api["forbidden_methods"] and not api["forbidden_imports"]
    signals = [lifecycle[name] for name in ("sigusr1", "sigterm", "sigint")]
    h4 = all(
        item["ready"]
        and item["fresh_start_no_stop"]
        and item["latched"]
        and item["exact_zero"]
        and item["stationary"]
        and item["lease_invalidated"]
        and item["return_code_zero"]
        and item["kept_running_after_signal"] == item["expected_keep_running"]
        for item in signals
    ) and all(
        (
            lifecycle["gateway_failure"]["ready"],
            lifecycle["gateway_failure"]["watchdog_before_failure"],
            not lifecycle["gateway_failure"]["watchdog_after_failure"],
            lifecycle["gateway_failure"]["nonzero_when_stop_unconfirmed"],
        )
    )
    h5 = composition["pass"] is True and all(composition["checks"].values())
    recomputed = {"SOS-H1": h1, "SOS-H2": h2, "SOS-H3": h3, "SOS-H4": h4, "SOS-H5": h5}
    return {
        "manifest_ok": body["manifest_sha256"] == manifest_sha,
        "digest_ok": digest_ok,
        "gates_ok": gates == recomputed,
        "all_functional_ok": body["all_functional_gates_pass"] is all(recomputed.values()),
        "physical_no_go": body["physical_readiness"] is False,
        "normalized_digest": claimed_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--run-a", required=True)
    parser.add_argument("--run-b", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    manifest = _load(manifest_path)
    hashes_ok = all(
        _sha256((REPO / name).read_bytes()) == digest
        for name, digest in manifest["files"].items()
    )
    manifest_sha = _sha256(manifest_path.read_bytes())
    run_a = _load(Path(args.run_a))
    run_b = _load(Path(args.run_b))
    a = _verify_one(run_a, manifest_sha)
    b = _verify_one(run_b, manifest_sha)
    equal = a["normalized_digest"] == b["normalized_digest"]

    tampered = json.loads(json.dumps(run_a))
    tampered["trials"]["latched"] = 255
    tamper_rejected = not _verify_one(tampered, manifest_sha)["digest_ok"]
    output = {
        "schema_version": 1,
        "study": "SOS-1",
        "source_hashes_ok": hashes_ok,
        "run_a": a,
        "run_b": b,
        "normalized_runs_equal": equal,
        "tamper_rejected": tamper_rejected,
    }
    output["pass"] = (
        hashes_ok
        and equal
        and tamper_rejected
        and all(
            item[key]
            for item in (a, b)
            for key in (
                "manifest_ok",
                "digest_ok",
                "gates_ok",
                "all_functional_ok",
                "physical_no_go",
            )
        )
    )
    Path(args.output).write_text(
        json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0 if output["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
