"""Static coupling audit for the portable Embodiment Kernel hypothesis."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

HIGH_LEVEL = {"attention", "brain", "memory", "realtime"}
ALLOWED_VENDOR_FILES = {
    "control/unitree_sport.py",
    "control/go2_sport_body_adapter.py",
    "backends/go2.py",
    "unitree_control.py",
}


def relative_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def imported_names(tree: ast.AST) -> list[str]:
    rows: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            rows.append(module)
            rows.extend(f"{module}.{alias.name}" for alias in node.names)
    return rows


def executable_vendor_names(tree: ast.AST) -> list[str]:
    rows: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and ("go2" in node.id.lower() or "unitree" in node.id.lower()):
            rows.add(node.id)
        elif isinstance(node, ast.Attribute):
            name = node.attr
            if "go2" in name.lower() or "unitree" in name.lower():
                rows.add(name)
    return sorted(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source_root = args.repo / "src/parcel_robot"

    sdk_leaks: list[dict[str, object]] = []
    high_level_vendor: list[dict[str, object]] = []
    sim_observation_modules: list[str] = []
    for path in relative_python_files(source_root):
        rel = path.relative_to(source_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = imported_names(tree)
        if any("unitree_sdk2" in name.lower() for name in imports) and rel not in ALLOWED_VENDOR_FILES:
            sdk_leaks.append({"module": rel, "imports": [name for name in imports if "unitree_sdk2" in name.lower()]})
        if rel.split("/", 1)[0] in HIGH_LEVEL:
            names = executable_vendor_names(tree)
            if names:
                high_level_vendor.append({"module": rel, "names": names})
        if rel.startswith(("backends/", "simulation/")):
            continue
        if any(name.endswith("SimObservation") for name in imports):
            sim_observation_modules.append(rel)

    service_files = sorted(
        path.relative_to(args.repo).as_posix()
        for path in (args.repo / "deploy").rglob("*.service")
    )
    deploy_readme = (args.repo / "deploy/README.md").read_text(encoding="utf-8")
    snapshot_hits = []
    for path in relative_python_files(source_root):
        if "NavigationSnapshotV2" in path.read_text(encoding="utf-8"):
            snapshot_hits.append(path.relative_to(source_root).as_posix())

    result = {
        "schema": "parcel.embodiment_kernel_audit.v1",
        "vendor_sdk_import_leaks": sdk_leaks,
        "high_level_vendor_name_references": high_level_vendor,
        "sim_observation_coupled_modules": sim_observation_modules,
        "navigation_snapshot_v2_modules": snapshot_hits,
        "deploy_service_files": service_files,
        "deploy_disclaims_orin_artifact": "No Orin flash" in deploy_readme,
        "rows": {
            "K1_vendor_sdk_leaks": len(sdk_leaks),
            "K2_high_level_vendor_modules": len(high_level_vendor),
            "K3_sim_observation_modules": len(sim_observation_modules),
            "K4_navigation_snapshot_v2_exists": bool(snapshot_hits),
            "K6_service_file_count": len(service_files),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

