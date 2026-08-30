#!/usr/bin/env python3
"""Create the policy-independent LHO-1 paired covering-array manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESIGN = ROOT / "DESIGN.md"
AMENDMENT = ROOT / "AMENDMENT_1_COVERING_ARRAY.md"
AMENDMENT_2 = ROOT / "AMENDMENT_2_PRE_EVIDENCE_AUDIT.md"
AMENDMENT_3 = ROOT / "AMENDMENT_3_FREEZE_READINESS.md"
LATENCIES = (0.10, 0.25, 0.40, 0.70, 1.10, 1.80)
ERRORS = (-0.50, -0.25, 0.0, 0.25, 0.50)
DECILES = tuple(range(1, 10))
SEEDS = (1207, 2029, 4093, 7211, 9001)

FAMILIES = (
    ("straight_open", 6.0, 0.60, 2.50, 0.20),
    ("s_turn", 7.0, 0.45, 1.80, 0.75),
    ("alternating_turns", 7.5, 0.40, 1.50, 1.00),
    ("narrow_corridor", 6.0, 0.35, 1.20, 0.45),
    ("t_shared_long", 6.5, 0.50, 2.00, 0.65),
    ("early_divergence", 7.0, 0.45, 1.00, 0.90),
    ("late_divergence", 7.0, 0.45, 2.00, 0.70),
    ("doorway", 5.5, 0.30, 0.80, 0.60),
    ("corner_90", 6.0, 0.40, 1.40, 0.85),
    ("hairpin", 7.0, 0.30, 1.00, 1.20),
    ("variable_corridor", 6.8, 0.45, 1.35, 0.80),
    ("open_plaza", 8.0, 0.60, 3.00, 0.30),
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unit_interval(*parts: object) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _case(
    *,
    family_index: int,
    seed_index: int,
    mode: str,
    decile: int | None,
    latency_index: int,
    error_index: int,
) -> dict[str, object]:
    family, length_m, max_speed_mps, corridor_cap_s, curvature = FAMILIES[family_index]
    seed = SEEDS[seed_index]
    key = f"{mode}|{family}|{seed}|{decile or 0}|{latency_index}|{error_index}"
    sense_jitter_s = round(0.08 * _unit_interval("sense", key), 6)
    command_jitter_s = round(0.05 * _unit_interval("command", key), 6)
    inference_jitter_s = round(-0.04 + 0.16 * _unit_interval("inference", key), 6)
    base_latency_s = LATENCIES[latency_index]
    actual_latency_s = round(
        max(0.05, base_latency_s + sense_jitter_s + command_jitter_s + inference_jitter_s),
        6,
    )
    event_fraction = None if decile is None else decile / 10.0
    event_at_m = None if event_fraction is None else round(length_m * event_fraction, 6)
    revised_length_m = round(length_m + 0.60 + 0.05 * (family_index % 5), 6)
    revised_speed_scale = round(0.58 + 0.03 * (family_index % 7), 6)
    case = {
        "case_id": _sha_bytes(key.encode("ascii"))[:24],
        "family": family,
        "family_index": family_index,
        "seed": seed,
        "mode": mode,
        "event_decile": decile,
        "event_fraction": event_fraction,
        "event_at_m": event_at_m,
        "length_m": length_m,
        "max_speed_mps": max_speed_mps,
        "revised_length_m": revised_length_m,
        "revised_speed_scale": revised_speed_scale,
        "original_tail_token": _sha_bytes(f"original|{family}|{seed}".encode("ascii"))[:16],
        "revised_tail_token": _sha_bytes(f"revised|{family}|{seed}".encode("ascii"))[:16],
        "max_accel_mps2": 1.2,
        "corridor_cap_s": corridor_cap_s,
        "curvature_gain": curvature,
        "planner_period_s": 1.2,
        "base_latency_s": base_latency_s,
        "actual_latency_s": actual_latency_s,
        "sense_jitter_s": sense_jitter_s,
        "command_jitter_s": command_jitter_s,
        "estimator_error": ERRORS[error_index],
        "tracker_hz": 20,
        "fixed_chunk_s": 0.4,
        "guard_margin_s": 0.1,
        "stop_command_deadline_s": 0.05,
        "obstacle_extra_braking_margin_m": 0.45,
        "robot_half_length_m": 0.35,
        "occupied_zone_start_m": event_at_m,
        "occupied_zone_end_m": (
            None if event_at_m is None else round(min(length_m, event_at_m + 0.60), 6)
        ),
        "occupied_contact_boundary_m": (
            None if event_at_m is None else round(event_at_m + 0.45, 6)
        ),
        "timeout_s": round(25.0 + 4.0 * length_m / max_speed_mps, 3),
    }
    case["case_sha256"] = _sha_bytes(_canonical(case))
    return case


def build_manifest() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for mode_index, mode in enumerate(("revision", "emergency", "occupied")):
        for family_index in range(len(FAMILIES)):
            for seed_index in range(len(SEEDS)):
                for decile_index, decile in enumerate(DECILES):
                    latency_index = (
                        family_index + 2 * seed_index + decile_index + mode_index
                    ) % len(LATENCIES)
                    error_index = (
                        2 * family_index + seed_index + 3 * decile_index + mode_index
                    ) % len(ERRORS)
                    cases.append(
                        _case(
                            family_index=family_index,
                            seed_index=seed_index,
                            mode=mode,
                            decile=decile,
                            latency_index=latency_index,
                            error_index=error_index,
                        )
                    )
    for family_index in range(len(FAMILIES)):
        for seed_index in range(len(SEEDS)):
            for latency_index in range(len(LATENCIES)):
                error_index = (family_index + seed_index + 2 * latency_index) % len(ERRORS)
                cases.append(
                    _case(
                        family_index=family_index,
                        seed_index=seed_index,
                        mode="control",
                        decile=None,
                        latency_index=latency_index,
                        error_index=error_index,
                    )
                )
    cases.sort(key=lambda item: str(item["case_id"]))
    coverage = {
        "cases": len(cases),
        "arm_episodes": len(cases) * 3,
        "families": len({item["family"] for item in cases}),
        "seeds": len({item["seed"] for item in cases}),
        "deciles": sorted({item["event_decile"] for item in cases if item["event_decile"]}),
        "latencies_s": sorted({item["base_latency_s"] for item in cases}),
        "estimator_errors": sorted({item["estimator_error"] for item in cases}),
        "modes": {
            mode: sum(item["mode"] == mode for item in cases)
            for mode in ("control", "revision", "emergency", "occupied")
        },
    }
    manifest: dict[str, object] = {
        "schema_version": 1,
        "study": "LHO-1",
        "evidence_tier": "deterministic scheduling/kinematic simulation",
        "design_sha256": _sha_bytes(DESIGN.read_bytes()),
        "amendment_sha256": _sha_bytes(AMENDMENT.read_bytes()),
        "amendment_2_sha256": _sha_bytes(AMENDMENT_2.read_bytes()),
        "amendment_3_sha256": _sha_bytes(AMENDMENT_3.read_bytes()),
        "coverage": coverage,
        "cases": cases,
    }
    manifest["manifest_sha256"] = _sha_bytes(_canonical(manifest))
    return manifest


def verify_manifest(manifest: dict[str, object]) -> None:
    expected = manifest.get("manifest_sha256")
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    if expected != _sha_bytes(_canonical(payload)):
        raise ValueError("manifest digest mismatch")
    if manifest.get("design_sha256") != _sha_bytes(DESIGN.read_bytes()):
        raise ValueError("design hash mismatch")
    if manifest.get("amendment_sha256") != _sha_bytes(AMENDMENT.read_bytes()):
        raise ValueError("amendment hash mismatch")
    if manifest.get("amendment_2_sha256") != _sha_bytes(AMENDMENT_2.read_bytes()):
        raise ValueError("amendment 2 hash mismatch")
    if manifest.get("amendment_3_sha256") != _sha_bytes(AMENDMENT_3.read_bytes()):
        raise ValueError("amendment 3 hash mismatch")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 1_980:
        raise ValueError("manifest must contain exactly 1,980 cases")
    if len({item["case_id"] for item in cases}) != len(cases):
        raise ValueError("case identities are not unique")
    for item in cases:
        row = dict(item)
        digest = row.pop("case_sha256", None)
        if digest != _sha_bytes(_canonical(row)):
            raise ValueError(f"case digest mismatch: {item.get('case_id')}")
    modes = {
        mode: sum(item["mode"] == mode for item in cases)
        for mode in ("control", "revision", "emergency", "occupied")
    }
    if modes != {"control": 360, "revision": 540, "emergency": 540, "occupied": 540}:
        raise ValueError(f"covering-array mode counts are wrong: {modes}")
    for mode in ("revision", "emergency", "occupied"):
        subset = [item for item in cases if item["mode"] == mode]
        cells = {(item["family_index"], item["seed"], item["event_decile"]) for item in subset}
        if len(cells) != 12 * 5 * 9:
            raise ValueError(f"{mode} does not contain every family/seed/decile cell")
        if {item["event_decile"] for item in subset} != set(DECILES):
            raise ValueError(f"{mode} does not cover every decile")
        if {item["base_latency_s"] for item in subset} != set(LATENCIES):
            raise ValueError(f"{mode} does not cover every latency")
        if {item["estimator_error"] for item in subset} != set(ERRORS):
            raise ValueError(f"{mode} does not cover every estimator error")
        pairs = {(item["base_latency_s"], item["estimator_error"]) for item in subset}
        if pairs != {(latency, error) for latency in LATENCIES for error in ERRORS}:
            raise ValueError(f"{mode} does not recur every latency/error pair")
    controls = [item for item in cases if item["mode"] == "control"]
    control_cells = {
        (item["family_index"], item["seed"], item["base_latency_s"]) for item in controls
    }
    if len(control_cells) != 12 * 5 * 6:
        raise ValueError("controls do not enumerate every family/seed/latency cell")
    regenerated = build_manifest()
    if _canonical(manifest) != _canonical(regenerated):
        raise ValueError("manifest differs from the deterministic generator")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "manifest.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        manifest = json.loads(args.output.read_text(encoding="utf-8"))
        verify_manifest(manifest)
    else:
        manifest = build_manifest()
        verify_manifest(manifest)
        args.output.write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "path": str(args.output),
                "sha256": manifest["manifest_sha256"],
                "coverage": manifest["coverage"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
