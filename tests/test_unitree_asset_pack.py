"""Card GATE-0 (``scrum/20260822/task_20``): the simulator payload is real.

Both product scenes — ``src/parcel_robot/scenes/city_block.xml`` and the
held-out ``city_block_b.xml`` — ``<include>`` the Unitree Go2 MJCF at
``third_party/unitree_mujoco/unitree_robots/go2/go2.xml``. Until this card that
directory was blanket-gitignored (``.gitignore``: ``third_party/``) and nothing
in the repository or in CI ever fetched it. The consequence was not a skipped
test; it was that on a fresh clone ``scripts/ci_gate.py --tier commit`` died
about one second in — the first gate to open a scene raised, the traceback
skipped every later gate, and ``--json`` never emitted. Four ``skipif`` guards
(three in ``test_sim.py``, one in ``test_dynamic_city.py``) quietly reported
"scene not checked out" instead of saying the simulator was absent, so nothing
in the suite ever said so either.

The fix is a **tracked, manifest-pinned 20-file subset** at the upstream path —
``PROVENANCE.json`` plus the BSD-3 ``LICENSE``, ``go2.xml``, ``scene.xml`` and
16 OBJ meshes, 27.1 MiB — vendored at upstream revision ``ae6a8403``. The path
is unchanged on purpose: the scenes' include lines and therefore the frozen
scene digests must not move.

This module is the closure contract, and the ``unitree-assets`` hard gate stage
in ``scripts/ci_gate.py`` is the same contract at gate time. It is deliberately
adversarial: every way the pack can rot has a seeded RED here.

**On the held-out scene.** This file names ``city_block_b`` and loads it. That
is a deliberate, allowlisted exposure recorded in ``tests/test_held_out_scene.py``:
this module compiles the scene's GEOMETRY and never renders a pixel, never
constructs a renderer, and never runs a model over it. Geometry is not the
held-out quantity — appearance is.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.ci_gate import (
    PRODUCT_SCENE_DIR,
    UNITREE_EXPECTED_REVISION,
    UNITREE_INCLUDE_TOKEN,
    UNITREE_PROVENANCE,
    UNITREE_ROOT,
    evaluate_unitree_assets,
    run_stage,
)

REPO = Path(__file__).resolve().parents[1]

#: The card's pre-registered ceiling. The full developer checkout this subset
#: came from is 296 MB of source and 76 MB of nested ``.git``; the payload the
#: product actually consumes is a rounding error next to it, and a repository
#: that ships 30 MB of vendored binary assets should have to notice growth.
PACK_BUDGET_BYTES = 30 * 1024 * 1024

#: Named literally so that "the held-out scene is covered by the asset gate" is
#: a statement this file makes, not one a glob makes silently on its behalf.
PRODUCT_SCENES = ("city_block.xml", "city_block_b.xml")


# ---------------------------------------------------------------------------
# The real pack, on this tree.
# ---------------------------------------------------------------------------


def _manifest() -> dict:
    return json.loads(UNITREE_PROVENANCE.read_text(encoding="utf-8"))


def test_the_pack_is_green_on_this_tree() -> None:
    result = evaluate_unitree_assets()
    assert result.status == "pass", result.detail
    assert result.hard, "a missing simulator payload is not an advisory"


def test_the_manifest_pins_the_reviewed_upstream_revision() -> None:
    manifest = _manifest()
    assert manifest["upstream_revision"] == UNITREE_EXPECTED_REVISION
    assert manifest["upstream_url"].endswith("unitree_mujoco.git")
    assert manifest["license"] == "BSD-3-Clause"
    assert (UNITREE_ROOT / manifest["license_file"]).is_file()


def test_the_pack_is_exactly_twenty_files_and_fits_the_budget() -> None:
    manifest = _manifest()
    paths = [entry["path"] for entry in manifest["files"]]
    assert len(paths) == len(set(paths)) == 19, "19 payload files + PROVENANCE.json = 20"
    total = sum(entry["size_bytes"] for entry in manifest["files"])
    assert total == manifest["total_bytes"]
    assert total <= PACK_BUDGET_BYTES, (
        f"the vendored pack is {total / 1_048_576:.1f} MiB, over the "
        f"{PACK_BUDGET_BYTES / 1_048_576:.0f} MiB budget this card pre-registered"
    )


def test_no_manifest_entry_carries_git_metadata_or_escapes_the_pack() -> None:
    """The nested 76 MB upstream clone must never become vendored content."""

    for entry in _manifest()["files"]:
        parts = entry["path"].split("/")
        assert ".git" not in parts, entry["path"]
        assert ".." not in parts, entry["path"]
        assert not entry["path"].startswith("/"), entry["path"]


def test_git_would_ship_the_pack_and_nothing_else_under_third_party() -> None:
    """The ``.gitignore`` carve-out is exact, not approximate.

    `third_party/` still holds four unrelated nested clones (CityWalker,
    fish-speech, llama.cpp, piper) and the 296 MB Unitree developer checkout the
    subset was taken from. Exposing any of that by accident is the failure mode
    a blanket ignore was hiding in the first place.
    """

    from scripts.ci_gate import _git_paths

    tracked, err_a = _git_paths("ls-files", "-z", "--", "third_party")
    untracked, err_b = _git_paths(
        "ls-files", "-z", "--others", "--exclude-standard", "--", "third_party"
    )
    if err_a or err_b:
        pytest.skip(f"git unavailable: {err_a or err_b}")
    shipped = tracked | untracked
    expected = {
        f"third_party/unitree_mujoco/{entry['path']}" for entry in _manifest()["files"]
    } | {"third_party/unitree_mujoco/PROVENANCE.json"}
    assert shipped == expected, (
        "the third_party/ carve-out no longer matches the manifest; "
        f"unmanifested={sorted(shipped - expected)[:8]} "
        f"hidden={sorted(expected - shipped)[:8]}"
    )
    assert len(shipped) == 20

    # Card FINISH-1 (task_29 §C3). Once the integrator's `git add` lands, the
    # pack is TRACKED, and a tracked file can go missing in a way `ls-files`
    # alone still reports as present: it stays in the index. `--deleted` is the
    # only listing that names it, and a mesh missing from the working tree is
    # the exact shape of seed E. Empty today (nothing under third_party/ is in
    # the index yet) and load-bearing the moment it is.
    deleted, err_c = _git_paths("ls-files", "-z", "--deleted", "--", "third_party")
    assert not err_c, err_c
    assert not deleted, f"tracked pack file(s) missing from the working tree: {sorted(deleted)}"


@pytest.mark.parametrize("scene_name", PRODUCT_SCENES)
def test_each_product_scene_compiles_from_the_tracked_pack(scene_name: str) -> None:
    """Geometry only. No renderer is constructed and no model is run.

    ``city_block_b.xml`` is the held-out scene; compiling it here is the
    allowlisted exposure recorded in ``tests/test_held_out_scene.py``.
    """

    import mujoco

    scene = PRODUCT_SCENE_DIR / scene_name
    assert UNITREE_INCLUDE_TOKEN in scene.read_text(encoding="utf-8")
    model = mujoco.MjModel.from_xml_path(str(scene))
    assert model.ngeom > 0
    # The Go2 body is what the pack contributes; without the meshes the compile
    # would have raised long before here.
    assert model.nmesh >= 16


def test_the_gate_covers_every_scene_that_includes_the_pack() -> None:
    """The stage derives its scene list; this asserts the derivation is total."""

    including = sorted(
        path.name
        for path in PRODUCT_SCENE_DIR.glob("*.xml")
        if UNITREE_INCLUDE_TOKEN in path.read_text(encoding="utf-8", errors="ignore")
    )
    assert including == sorted(PRODUCT_SCENES), (
        "a product scene started or stopped including the Unitree pack; the "
        "asset gate compiles whatever it finds, but this list is the record of "
        "what anyone reviewed"
    )


# ---------------------------------------------------------------------------
# SEEDED RED. A synthetic pack under tmp_path, so the owner's 27 MiB of real
# assets are never written to. The stage records the git-closure sub-check as
# SKIPPED for a root outside the repository rather than passing it vacuously,
# which is itself asserted below.
# ---------------------------------------------------------------------------

_FAKE_GO2 = """<mujoco model="fake go2">
  <worldbody>
    <body name="trunk" pos="0 0 0.3">
      <geom name="trunk" type="box" size="0.1 0.05 0.03"/>
    </body>
  </worldbody>
</mujoco>
"""

_FAKE_SCENE = """<mujoco model="fake city">
  <include file="../../../third_party/unitree_mujoco/unitree_robots/go2/go2.xml"/>
  <worldbody>
    <geom name="floor" type="plane" size="5 5 0.1"/>
  </worldbody>
</mujoco>
"""


@pytest.fixture
def fake_pack(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A miniature repo layout: ``(pack_root, provenance, scene_dir)``."""

    import hashlib

    root = tmp_path / "third_party" / "unitree_mujoco"
    (root / "unitree_robots" / "go2" / "assets").mkdir(parents=True)
    (root / "LICENSE").write_text("BSD 3-Clause License\n", encoding="utf-8")
    (root / "unitree_robots" / "go2" / "go2.xml").write_text(_FAKE_GO2, encoding="utf-8")
    (root / "unitree_robots" / "go2" / "assets" / "base_0.obj").write_text(
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n", encoding="utf-8"
    )

    files = []
    for rel in ("LICENSE", "unitree_robots/go2/go2.xml", "unitree_robots/go2/assets/base_0.obj"):
        blob = (root / rel).read_bytes()
        files.append(
            {"path": rel, "size_bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
        )
    provenance = root / "PROVENANCE.json"
    provenance.write_text(
        json.dumps(
            {
                "upstream_revision": UNITREE_EXPECTED_REVISION,
                "upstream_url": "https://github.com/unitreerobotics/unitree_mujoco.git",
                "license": "BSD-3-Clause",
                "license_file": "LICENSE",
                "files": files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    scene_dir = tmp_path / "src" / "parcel_robot" / "scenes"
    scene_dir.mkdir(parents=True)
    (scene_dir / "fake_city.xml").write_text(_FAKE_SCENE, encoding="utf-8")
    return root, provenance, scene_dir


def _evaluate(pack: tuple[Path, Path, Path]):
    root, provenance, scene_dir = pack
    return evaluate_unitree_assets(root=root, provenance=provenance, scene_dir=scene_dir)


def test_the_synthetic_control_is_green(fake_pack) -> None:
    """The control. Without this, every seeded RED below could be red for the
    wrong reason and nobody would know."""

    result = _evaluate(fake_pack)
    assert result.status == "pass", result.detail
    assert "shipping closure: SKIPPED" in result.detail, (
        "a pack outside the repository has no closure to check; it must be "
        "recorded as skipped, never silently passed"
    )
    assert "fake_city.xml: compiled" in result.detail


def test_a_deleted_payload_reddens(fake_pack) -> None:
    root, _, _ = fake_pack
    (root / "unitree_robots" / "go2" / "assets" / "base_0.obj").unlink()
    result = _evaluate(fake_pack)
    assert result.status == "fail"
    assert "missing from the checkout" in result.detail


def test_one_tampered_byte_reddens(fake_pack) -> None:
    root, _, _ = fake_pack
    target = root / "unitree_robots" / "go2" / "assets" / "base_0.obj"
    blob = bytearray(target.read_bytes())
    blob[0] ^= 0x01
    target.write_bytes(bytes(blob))
    result = _evaluate(fake_pack)
    assert result.status == "fail"
    assert "sha256" in result.detail


def test_a_size_only_change_reddens(fake_pack) -> None:
    root, _, _ = fake_pack
    target = root / "unitree_robots" / "go2" / "assets" / "base_0.obj"
    target.write_bytes(target.read_bytes() + b"v 9 9 9\n")
    result = _evaluate(fake_pack)
    assert result.status == "fail"
    assert "bytes on disk" in result.detail


def test_a_self_consistent_pack_at_the_wrong_revision_reddens(fake_pack) -> None:
    """The reason the expected revision is pinned in ``ci_gate.py`` and not
    read out of the manifest: a swapped pack validates against its own
    paperwork perfectly."""

    _, provenance, _ = fake_pack
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    payload["upstream_revision"] = "0" * 40
    provenance.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    result = _evaluate(fake_pack)
    assert result.status == "fail"
    assert "upstream_revision" in result.detail


@pytest.mark.parametrize(
    "unsafe",
    ["../../../../etc/passwd", "/etc/passwd", ".git/config", "unitree_robots/../../escape"],
)
def test_an_unsafe_manifest_path_reddens_before_it_is_opened(fake_pack, unsafe: str) -> None:
    _, provenance, _ = fake_pack
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    payload["files"].append({"path": unsafe, "size_bytes": 0, "sha256": "0" * 64})
    provenance.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    result = _evaluate(fake_pack)
    assert result.status == "fail"
    assert "unsafe manifest path" in result.detail


def test_a_missing_manifest_reddens_rather_than_raising(fake_pack) -> None:
    _, provenance, _ = fake_pack
    provenance.unlink()
    result = _evaluate(fake_pack)
    assert result.status == "fail"
    assert "MISSING" in result.detail


def test_an_unparseable_manifest_reddens_rather_than_raising(fake_pack) -> None:
    _, provenance, _ = fake_pack
    provenance.write_text("{not json", encoding="utf-8")
    result = _evaluate(fake_pack)
    assert result.status == "fail"
    assert "unparseable" in result.detail


def test_a_scene_that_cannot_compile_reddens_with_a_named_result(fake_pack) -> None:
    """MuJoCo raises ``ValueError`` out of ``from_xml_path``. That exception is
    the one that used to end the whole gate run; here it must become a row."""

    root, _, _ = fake_pack
    (root / "unitree_robots" / "go2" / "go2.xml").write_text(
        "<mujoco><worldbody><geom type=\"nonsense\"/></worldbody></mujoco>", encoding="utf-8"
    )
    result = _evaluate(fake_pack)
    assert result.status == "fail"
    assert result.name == "unitree-assets"
    assert "does not compile" in result.detail


def test_a_pack_with_no_including_scene_reddens(fake_pack, tmp_path: Path) -> None:
    """A gate that compiles nothing must not report success."""

    root, provenance, _ = fake_pack
    empty = tmp_path / "no_scenes"
    empty.mkdir()
    result = evaluate_unitree_assets(root=root, provenance=provenance, scene_dir=empty)
    assert result.status == "fail"
    assert "includes the pack" in result.detail


def test_a_tracked_gitlink_reddens(fake_pack, monkeypatch) -> None:
    """A submodule pointer is the other way the pack can look present and be
    absent — IG-1's "never track a gitlink"."""

    import scripts.ci_gate as gate

    real = gate._git_paths

    def fake(*args: str):
        if "-s" in args:
            return {"160000 0000000000000000000000000000000000000000 0\tthird_party/unitree_mujoco"}, None
        return real(*args)

    monkeypatch.setattr(gate, "_git_paths", fake)
    result = gate.evaluate_unitree_assets()
    assert result.status == "fail"
    assert "gitlink" in result.detail


def test_an_unmanifested_file_smuggled_through_the_carve_out_reddens(monkeypatch) -> None:
    """SEED. An extra shippable path under the pack is a hard red.

    **Redesigned by FINISH-1 (task_29 §C1) and here is what it used to do.** It
    wrote a real probe ``.obj`` INTO ``third_party/unitree_mujoco/.../assets/``
    and removed it in a ``finally``. Two ways that hurt, both reproduced by the
    verifier: under ``pytest -n auto`` any other test that evaluates the pack in
    the same wall-clock window sees the probe and reddens for a defect that is
    not there (reproduced at ``-n 26`` and ``-n auto``), and a SIGKILL between
    the write and the ``finally`` leaves a stray file in a vendored directory
    that every later run blames on the pack.

    The closure check is a **set comparison** — ``shipped - expected`` — and it
    never opens the extra path, so the seed does not need the file to exist. The
    gitlink seed above already establishes the pattern: monkeypatch
    ``_git_paths`` and let everything else be the product's. Nothing is written
    anywhere, and the test is safe at any worker count.

    The premise the old write proved — that ``.gitignore``'s carve-out really
    would ship a stray ``.obj`` — is not dropped: it is proved against real git
    in a throwaway repository by the test below.
    """

    import scripts.ci_gate as gate

    real = gate._git_paths
    smuggled = "third_party/unitree_mujoco/unitree_robots/go2/assets/_gate0_probe.obj"

    def fake(*args: str):
        paths, err = real(*args)
        # ``--others`` is the untracked half: a stray that the carve-out
        # un-ignores appears exactly here, which is how a real one would.
        if "--others" in args and err is None:
            return paths | {smuggled}, None
        return paths, err

    monkeypatch.setattr(gate, "_git_paths", fake)
    result = gate.evaluate_unitree_assets()
    assert result.status == "fail", result.detail
    assert "does not declare" in result.detail
    assert "_gate0_probe.obj" in result.detail

    monkeypatch.undo()
    assert gate.evaluate_unitree_assets().status == "pass", "the seed must leave no trace"


def test_the_gitignore_carve_out_really_would_ship_a_stray_obj(tmp_path: Path) -> None:
    """The premise behind the seed above, proved against real git — in tmp.

    ``.gitignore`` un-ignores ``assets/*.obj`` by glob (lines 88–89), so any
    ``.obj`` dropped beside the meshes is genuinely shippable and genuinely
    invisible to every other check in this file. This copies the REPOSITORY'S
    OWN ``.gitignore`` into a throwaway ``git init`` and asks git itself. The
    real pack directory is never touched, and nothing is ever staged.
    """

    import subprocess

    proc = subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True, check=False)
    if proc.returncode != 0:  # pragma: no cover - no git binary
        pytest.skip("git is unavailable")
    shutil.copyfile(REPO / ".gitignore", tmp_path / ".gitignore")
    assets = tmp_path / "third_party" / "unitree_mujoco" / "unitree_robots" / "go2" / "assets"
    assets.mkdir(parents=True)
    (assets / "_stray.obj").write_text("v 0 0 0\n", encoding="utf-8")
    (assets / "_stray.txt").write_text("not a mesh\n", encoding="utf-8")

    listed = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=True,
    ).stdout.split()

    suffix = "third_party/unitree_mujoco/unitree_robots/go2/assets"
    assert f"{suffix}/_stray.obj" in listed, "the carve-out would ship a stray mesh"
    assert f"{suffix}/_stray.txt" not in listed, "everything else stays ignored"


def test_the_stage_wrapper_turns_an_exploding_pack_check_into_a_row(monkeypatch) -> None:
    """Belt and braces: even a defect in this evaluator cannot end the run."""

    def boom(**_kwargs):
        raise RuntimeError("seeded: the asset evaluator itself is broken")

    results = run_stage("unitree-assets", lambda: boom(), tier="commit")
    assert len(results) == 1
    assert results[0].name == "unitree-assets"
    assert results[0].status == "error"
    assert results[0].hard
    assert "RuntimeError" in results[0].detail


# ---------------------------------------------------------------------------
# The escape hatches this card removed stay removed.
# ---------------------------------------------------------------------------


def test_no_test_skips_itself_for_a_missing_go2_scene() -> None:
    """Four ``skipif`` guards used to report "scene not checked out" on a clean
    clone. With the pack tracked, that reason is unreachable, and a guard that
    can never fire is a delete button with a friendly message."""

    offenders = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped.startswith("@pytest.mark.skipif"):
                continue
            if "Go2 scene" in stripped or "unitree_mujoco" in stripped:
                offenders.append(f"{path.name}: {stripped}")
    assert not offenders, (
        "these tests still skip themselves when the simulator payload is "
        f"absent, which is now a hard gate failure instead: {offenders}"
    )


def test_the_developer_checkout_is_not_what_ships(tmp_path: Path) -> None:
    """A cheap sanity check on the whole premise: the pack is self-contained.

    Copy just the 20 manifest files into an empty tree, point a copy of the real
    product scenes at it, and compile. If anything in the pack reached sideways
    into the 296 MB developer checkout, this is where it shows.
    """

    import mujoco

    root = tmp_path / "third_party" / "unitree_mujoco"
    for entry in _manifest()["files"]:
        dest = root / entry["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(UNITREE_ROOT / entry["path"], dest)

    scenes = tmp_path / "src" / "parcel_robot" / "scenes"
    shutil.copytree(PRODUCT_SCENE_DIR, scenes)
    for name in PRODUCT_SCENES:
        model = mujoco.MjModel.from_xml_path(str(scenes / name))
        assert model.ngeom > 0
