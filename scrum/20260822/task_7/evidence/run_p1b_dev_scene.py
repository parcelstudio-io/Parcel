"""Card P1-B — the dev-scene proof: the RUNTIME's own map, written from pixels.

MOVE-1's harness (``scrum/20260821/task_20/evidence/run_move1_patrol.py``)
built the map ITSELF, outside the robot, from ``camera_detection_frame_slice``.
This runs the same patrol and does not: the map is the one the RUNTIME owns,
installed by ``RobotRuntime._p1b_install_learned_map`` under
``perception.semantic_source``, fed by ``_publish_camera_frame``, and persisted
by ``close()``. The harness only reads the result back — from the STORE, in a
fresh process, which is the only way "it persisted" is a claim and not a hope.

Measured rows are pre-registered in ``../P1B_PREREGISTRATION.md``.
"""

from __future__ import annotations

import os

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("PARCEL_SIGLIP2_ONNX", "1")

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scrum" / "20260821" / "task_20" / "evidence"))

CONFIG = """
skills:
  root: {skills}
simulation:
  scene: {scene}
navigation:
  enabled: true
  config: {nav_config}
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
perception:
  spatial_sensors: [camera, lidar]
  camera_ingress: true
  camera_ingress_rate_hz: 2.0
  camera_ingress_queue_capacity: 64
  camera_ingress_max_detections_per_frame: 8
  camera_ingress_queries: [{queries}]
"""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=120.0)
    parser.add_argument("--scene", default="city_block")
    parser.add_argument("--nav-config", default="configs/navigation/prototype.yaml")
    parser.add_argument("--out", default=None)
    # Reuse an existing store to prove the OTHER half of persistence: a second
    # run reloads what the first one learned. "The dog that walked yesterday
    # knows the lamppost today" is only a claim if two runs share a file.
    parser.add_argument("--store", default=None)
    args = parser.parse_args()

    from run_move1_diagnosis import sha256_file, start_simulator, stop_simulator

    from parcel_robot.models import VelocityCommand
    from parcel_robot.online_map import OnlineMapStore
    from parcel_robot.patrol import (
        MapGrowthSample,
        PatrolLimits,
        PatrolRunner,
        ingress_queries,
        sense_from_snapshot,
    )
    from parcel_robot.web_panel import build_runtime

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out or (Path(__file__).parent / f"p1b_{args.scene}_{stamp}"))
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = REPO / "src" / "parcel_robot" / "scenes" / f"{args.scene}.xml"
    if not scene.is_file():
        raise SystemExit(f"no such scene: {scene}")

    scratch = Path.home() / ".cache" / "parcel-p1b"
    scratch.mkdir(parents=True, exist_ok=True)
    store_path = Path(args.store) if args.store else scratch / f"p1b_map_{stamp}.sqlite3"
    os.environ["PARCEL_ONLINE_MAP_PATH"] = str(store_path)

    batch = ingress_queries(6)
    config_path = out_dir / "p1b.yaml"
    config_path.write_text(
        CONFIG.format(
            skills=REPO / "configs" / "skills",
            scene=scene,
            nav_config=args.nav_config,
            queries=", ".join(batch),
        ),
        encoding="utf-8",
    )

    # Verification correction, 2026-08-22. This read
    # ``~/.parcel/parcel_memory.sqlite3``, inherited from MOVE-1's harness.
    # THAT FILE DOES NOT EXIST on this host, so every run reported
    # {before: None, after: None, unchanged: True} and the "the owner's store
    # was not touched" claim was VACUOUS — it would have been True with the
    # real store on fire. ``memory_path.owner_store_paths`` is the same
    # authority the online map's own R27 refusal uses, so the harness and the
    # guard now name one file. Read-only: hashed, never opened for write.
    from parcel_robot.memory_path import owner_store_paths

    owner_store = Path(owner_store_paths()[0])
    owner_before = sha256_file(owner_store) if owner_store.is_file() else None

    socket_path = scratch / f"sim-{os.getpid()}.sock"
    process, handle = start_simulator(
        config_path=config_path,
        socket_path=socket_path,
        log_path=out_dir / "simulator.log",
        static_city=False,
    )
    live: dict[str, object] = {}
    try:
        runtime = build_runtime(config_path, socket_path, use_llm=False)
        runtime.start()
        try:

            def sense_provider(elapsed: float):
                return sense_from_snapshot(runtime.snapshot(), elapsed_s=elapsed)

            def submit(command) -> bool:
                try:
                    runtime.submit_motion(
                        "voice",
                        VelocityCommand(
                            vx=command.vx, vy=command.vy, vyaw=command.vyaw
                        ),
                    )
                except Exception:  # noqa: BLE001
                    return False
                return True

            def map_probe() -> MapGrowthSample:
                snap = runtime.learned_map_snapshot() or {}
                learned = runtime._p1b_learned_map
                entries = learned.entries() if learned is not None else ()
                return MapGrowthSample(
                    t_s=0.0,
                    entries=len(entries),
                    labels=tuple(sorted({e.label for e in entries})),
                    frames_seen=int(snap.get("frames_ingested", 0) or 0),
                    detections_seen=int(snap.get("observations", 0) or 0),
                )

            runner = PatrolRunner(
                scene=args.scene,
                sense_provider=sense_provider,
                submit=submit,
                map_probe=map_probe,
                limits=PatrolLimits(budget_s=args.budget),
            )
            report = runner.run()
            live["map_snapshot"] = runtime.learned_map_snapshot()
            live["camera_snapshot"] = runtime.camera_stream_snapshot()
            learned = runtime._p1b_learned_map
            rows_live = learned.entries() if learned else ()
            live["in_memory"] = _describe(rows_live)
            # THE fidelity subject: the writer's own serialization, which is
            # exactly the bytes ``OnlineMapStore.save`` persists. Comparing a
            # live dataclass field against a reloaded one would fail on
            # ``as_dict``'s 4-place rounding and say nothing about the store.
            live["as_dict_sha256"] = _corpus_sha(rows_live)
        finally:
            runtime.close()
    finally:
        returncode = stop_simulator(process, handle, socket_path)

    # ------ the claim: reload the STORE in this process, from disk ------
    reloaded: dict[str, object] = {"store": str(store_path)}
    # The store opens journal_mode=WAL. If the runtime did not checkpoint on
    # close, the newest rows are in this sidecar and the .sqlite3 is stale —
    # so its presence is recorded BEFORE anything opens the store (opening
    # would create one).
    reloaded["wal_sidecar_present"] = store_path.with_name(
        store_path.name + "-wal"
    ).exists()
    reloaded["store_sha256_before_reopen"] = (
        sha256_file(store_path) if store_path.is_file() else None
    )
    if store_path.is_file():
        store = OnlineMapStore(store_path)
        rows = store.load_all()
        reloaded["schema"] = store.get_meta("schema")
        reloaded["origin_meta"] = store.get_meta("origin")
        reloaded["entries"] = _describe(rows)
        reloaded["as_dict_sha256"] = _corpus_sha(rows)
        reloaded["store_sha256"] = sha256_file(store_path)
        store.close()
    else:
        reloaded["error"] = "no store file was written"

    before_rows = live.get("in_memory") or []
    after_rows = reloaded.get("entries") or []
    fidelity = {
        "in_memory_entries": len(before_rows),
        "reloaded_entries": len(after_rows),
        "as_dict_sha256_before": live.get("as_dict_sha256"),
        "as_dict_sha256_after": reloaded.get("as_dict_sha256"),
        "as_dict_identical": live.get("as_dict_sha256")
        == reloaded.get("as_dict_sha256"),
        "thumbnails_identical": [
            r["thumbnail_sha256"] for r in before_rows
        ]
        == [r["thumbnail_sha256"] for r in after_rows],
    }

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "card": "P1-B",
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        ).stdout.strip(),
        "scene": str(scene),
        "scene_sha256": sha256_file(scene),
        "navigation_config": args.nav_config,
        "query_vocabulary": list(batch),
        "simulator_returncode": returncode,
        "owner_store": {
            "path": str(owner_store),
            "existed": owner_store.is_file(),
            "sha256_before": owner_before,
            "sha256_after": (
                sha256_file(owner_store) if owner_store.is_file() else None
            ),
            # A None==None "unchanged" is not evidence; say so in the row.
            "unchanged": bool(owner_before)
            and owner_before
            == (sha256_file(owner_store) if owner_store.is_file() else None),
        },
        "live": live,
        "reloaded": reloaded,
        "fidelity": fidelity,
        "report": report.as_dict(),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(_headline(payload), indent=2))
    print(f"\nwrote {out_dir}/summary.json")


def _corpus_sha(entries) -> str:
    """sha256 over every entry's ``as_dict()``. The writer's own bytes."""

    return hashlib.sha256(
        json.dumps([e.as_dict() for e in entries], sort_keys=True).encode("utf-8")
    ).hexdigest()


def _describe(entries) -> list[dict]:
    rows = []
    for entry in entries:
        stamp = entry.embedding_stamp
        rows.append(
            {
                "entry_id": entry.entry_id,
                "label": entry.label,
                "status": entry.status,
                "surface": [
                    round(float(entry.surface_x), 4),
                    round(float(entry.surface_y), 4),
                    round(float(entry.surface_z), 4),
                ],
                "evidence_frames": entry.evidence_frames,
                "detection_count": entry.detection_count,
                "hygiene_note": entry.hygiene_note,
                # Rounded to the store's own precision: ``as_dict`` rounds to 4
                # places, so an unrounded live value would "differ" from its
                # own persisted form and say nothing about fidelity.
                "relief_m": (
                    None if entry.relief_m is None else round(float(entry.relief_m), 4)
                ),
                "embedding_space": None if stamp is None else stamp.space_key,
                "embedding_dim": None if stamp is None else stamp.dim,
                "thumbnail_sha256": (
                    sha256_bytes(entry.thumbnail) if entry.thumbnail else None
                ),
                "thumbnail_bytes": len(entry.thumbnail) if entry.thumbnail else 0,
                "origin": entry.provenance.origin,
                "scene_id": entry.provenance.scene_id,
                "seat": entry.provenance.seat,
                "first_seen_wall_s": round(float(entry.first_seen_wall_s), 3),
            }
        )
    return sorted(rows, key=lambda r: r["entry_id"])


def _headline(payload: dict) -> dict:
    rows = payload["reloaded"].get("entries") or []
    total = len(rows) or 1
    return {
        "entries_reloaded": len(rows),
        "labels": sorted({r["label"] for r in rows}),
        "embedded_fraction": round(
            sum(1 for r in rows if r["embedding_space"]) / total, 4
        ),
        "relief_measured_fraction": round(
            sum(1 for r in rows if r["relief_m"] is not None) / total, 4
        ),
        "thumbnail_fraction": round(
            sum(1 for r in rows if r["thumbnail_bytes"]) / total, 4
        ),
        "origins": sorted({r["origin"] for r in rows}),
        "fidelity": payload["fidelity"],
        "wal_sidecar_present": payload["reloaded"].get("wal_sidecar_present"),
        "store_sha256": payload["reloaded"].get("store_sha256_before_reopen"),
        "as_dict_corpus_sha256": payload["reloaded"].get("as_dict_sha256"),
        "scene_ids": sorted({r["scene_id"] for r in rows}) if rows else [],
        "map_snapshot": payload["live"].get("map_snapshot"),
        "owner_store": {
            k: payload["owner_store"][k] for k in ("path", "existed", "unchanged")
        },
        "owner_store_sha256": payload["owner_store"]["sha256_after"],
        "patrol": {
            k: payload["report"].get(k)
            for k in ("path_length_m", "elapsed_s", "stopped_reason", "collision_ticks")
        },
    }


if __name__ == "__main__":
    main()
