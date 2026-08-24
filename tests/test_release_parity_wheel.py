"""N27 — the built wheel is the artifact under test (nightly).

``tests/test_release_parity.py`` proves the packaged tree mirrors source in the
checkout. That is necessary but not sufficient: ``package-data`` globs decide
what actually lands in the wheel, and a source-side mirror can be perfect while
the wheel ships a partial tree. These tests build a wheel, install it into an
empty venv, and compare *resolved effective configuration* — not files present.

Resolved values matter because a missing packaged file degrades silently:
``navigation/pipeline.py`` catches the read failure for ``configs/navigation/
pose.yaml`` and substitutes a default inside-probability threshold that happens
to equal the file's own current value, so nothing reports the difference.

Nightly only: this builds a wheel and needs the build backend.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from parcel_robot.paths import load_packaged_manifest

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "tools" / "release_parity_probe.py"
SCRATCH = REPO / ".tmp_ci"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not os.environ.get("PARCEL_NIGHTLY"),
        reason="nightly: builds a wheel and creates an empty venv",
    ),
]


@pytest.fixture(scope="module")
def wheel() -> Path:
    SCRATCH.mkdir(exist_ok=True)
    outdir = SCRATCH / "n27-wheel"
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(outdir)],
        capture_output=True, text=True, cwd=str(REPO), check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"wheel build failed (build backend missing?):\n{proc.stderr[-2000:]}")
    wheels = sorted(outdir.glob("parcel_robot_dog-*.whl")) or sorted(outdir.glob("*.whl"))
    assert wheels, f"no wheel produced in {outdir}"
    return wheels[0]


@pytest.fixture(scope="module")
def installed_venv(wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    venv = tmp_path_factory.mktemp("n27-venv") / "v"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / "bin" / "python"
    proc = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", str(wheel)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"wheel install failed:\n{proc.stderr[-2000:]}")
    return python


def _run_in(python: Path, code: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd)}  # PARCEL_ROOT deliberately unset
    return subprocess.run(
        [str(python), "-c", code], capture_output=True, text=True,
        cwd=str(cwd), env=env, check=False,
    )


def test_built_wheel_contains_every_manifest_path(wheel: Path) -> None:
    """Asserted against the wheel's zip namelist, not the repo tree."""

    members = set(zipfile.ZipFile(wheel).namelist())
    manifest = load_packaged_manifest()
    missing = [
        entry["packaged"]
        for entry in manifest["assets"]
        if f"parcel_robot/runtime_assets/{entry['packaged']}" not in members
    ]
    assert not missing, f"wheel is missing packaged assets: {missing}"
    assert "parcel_robot/runtime_assets/MANIFEST.json" in members
    for entry in manifest["side_mirrors"]:
        member = entry["target"].replace("src/", "", 1)
        assert member in members, f"wheel is missing the side mirror {member}"


def test_wheel_imports_the_previously_broken_modules(installed_venv: Path, tmp_path: Path) -> None:
    """city_semantics resolves its sidecar at module scope; pose.yaml must load."""

    result = _run_in(
        installed_venv,
        "import parcel_robot.perception.city_semantics as c;"
        "from parcel_robot.pose import load_pose_config;"
        "load_pose_config();"
        "print('ok')",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ok" in result.stdout


def test_every_default_asset_resolves_inside_the_installed_wheel(
    installed_venv: Path, tmp_path: Path
) -> None:
    from tests.test_release_parity import DEFAULT_DIR_ASSETS, DEFAULT_FILE_ASSETS

    code = (
        "import json;from pathlib import Path;"
        "from parcel_robot.paths import resolve_asset, packaged_assets_root;"
        f"files={list(DEFAULT_FILE_ASSETS)!r};dirs={list(DEFAULT_DIR_ASSETS)!r};"
        "pkg=packaged_assets_root();out={};"
        "out.update({r: resolve_asset(*Path(r).parts, kind='file').is_relative_to(pkg) for r in files});"
        "out.update({r: resolve_asset(*Path(r).parts, kind='dir').is_relative_to(pkg) for r in dirs});"
        "print(json.dumps(out))"
    )
    result = _run_in(installed_venv, code, tmp_path)
    assert result.returncode == 0, result.stderr[-2000:]
    resolved = json.loads(result.stdout)
    outside = [name for name, inside in resolved.items() if not inside]
    assert not outside, f"resolved outside the installed package: {outside}"


def test_wheel_effective_config_equals_the_source_checkout(
    installed_venv: Path, tmp_path: Path
) -> None:
    """The card's exit criterion, compared component-by-component."""

    probe = tmp_path / "release_parity_probe.py"
    shutil.copy2(PROBE, probe)

    wheel_side = _run_in(installed_venv, probe.read_text(encoding="utf-8"), tmp_path)
    assert wheel_side.returncode == 0, wheel_side.stderr[-2000:]
    wheel_config = json.loads(wheel_side.stdout)

    source_side = subprocess.run(
        [sys.executable, str(PROBE)], capture_output=True, text=True,
        cwd=str(REPO), check=True,
    )
    source_config = json.loads(source_side.stdout)

    errored = {k: v for k, v in wheel_config["components"].items() if str(v).startswith("ERROR:")}
    assert not errored, f"components failed to load in the wheel: {errored}"

    differing = [
        name
        for name, digest in source_config["components"].items()
        if wheel_config["components"].get(name) != digest
    ]
    assert not differing, (
        f"effective configuration differs between source and wheel: {differing}\n"
        f"source={source_config['components']}\nwheel={wheel_config['components']}"
    )
    assert source_config["digest"] == wheel_config["digest"]
