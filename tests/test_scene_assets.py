"""Card W-1: the textured world, and the proof that texturing it is visual-only.

The 2026-08-21 detector bench (`scrum/20260821/perception/bench_detectors.md`)
established that no perception number measured in the untextured `city_block`
means anything: three open-vocabulary detectors scored **0/69** person recall on
its renders and 81-93% on real photos, and a VLM described the block as
"colorful geometric shapes". W-1 gave the block photo-derived CC0 textures,
storefronts with signage, and textured human meshes for the dynamic agents.

Everything that made that safe is pinned here, because "textures cannot move
physics" is a claim, and a claim without a test is a hope:

* **The collision signature is frozen.** Every geom that can collide, with its
  type, size, pose, friction, solref/solimp, margin and gap, hashed. The pin
  below is the value computed from the scene as it stood BEFORE W-1 touched it,
  so a collision geom that moves is a red build no matter which card moves it.
* **Every geom W-1 added is `vis_*`, non-colliding and massless**, and `vis_`
  matches no obstacle prefix, no semantics prefix and no orbit-clearance prefix
  — so nothing added for looks can become an obstacle, a semantic instance, a
  navigation candidate or a mass.
* **Every asset the scene references exists** and matches the digest recorded in
  `assets/PROVENANCE.json`, so a broken texture path or a hand-edited PNG is a
  red build rather than a silently untextured render.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("MUJOCO_GL", "egl")

import mujoco

from parcel_robot.perception.city_semantics import OBJECT_PREFIX_TABLE, REGION_PREFIX_TABLE
from parcel_robot.sim import LOGICAL_OBSTACLE_PREFIXES, is_logical_obstacle_name
from parcel_robot.simulation.headless_city import _STATIC_OBSTACLE_PREFIXES

REPO = Path(__file__).resolve().parents[1]
SCENES = REPO / "src" / "parcel_robot" / "scenes"
CITY = SCENES / "city_block.xml"
HELD_OUT = SCENES / "city_block_b.xml"
ASSETS = SCENES / "assets"
PROVENANCE = ASSETS / "PROVENANCE.json"

#: The namespace every visual-only geom this card added lives in. One prefix,
#: chosen so that a reader can grep it, and so that the four prefix tables below
#: can be checked against it once rather than per geom.
VISUAL_PREFIX = "vis_"

#: sha256 over the canonical serialisation of every COLLIDING geom in
#: `city_block.xml`. Measured on the scene at commit 8473a51 — i.e. before W-1
#: existed — and unchanged by W-1. If this moves, something changed the physics
#: of the block and every frozen nav baseline measured against it is stale.
#: Re-pinning it is a deliberate act that needs the same evidence a frozen
#: digest re-pin needs.
CITY_COLLISION_SIGNATURE = "4e3e13e37a99f79d26e9fbff3f3241028ed301b4f4a049a1ce830b8870d41537"
CITY_COLLIDING_GEOM_COUNT = 68

#: sha256 over every body's mass, inertia, inertial frame and body frame.
#: Same provenance as the collision pin: measured before W-1 and unchanged by
#: it. This is the pin a forgotten ``density="0"`` trips — a visual mesh with
#: MuJoCo's default density adds ~2.6 tonnes to a pedestrian body, which is not
#: a dynamics change for a mocap actor but IS a model change, and the difference
#: between "harmless here" and "harmless" is the kind of thing a scene edit
#: should never be trusted to know.
CITY_INERTIAL_SIGNATURE = "a3317ea93af3c6f728aaeaecea2cceb7e9f70638ec515a0364ced99ce4ea8b43"
CITY_BODY_COUNT = 27

#: The exact set of geom names `sim.is_logical_obstacle_name` matches. Frozen
#: because that predicate feeds the LiDAR obstacle payload and the reactive stop
#: — a decorative geom that lands in this namespace becomes something the robot
#: brakes for, silently and without touching a line of navigation code.
CITY_LOGICAL_OBSTACLE_SIGNATURE = (
    "8cbc7b94b5519b2297c281c098d179aace1fe6036ece03703ddc2961517e198c"
)
CITY_LOGICAL_OBSTACLE_COUNT = 44


@pytest.fixture(scope="module")
def city() -> mujoco.MjModel:
    return mujoco.MjModel.from_xml_path(str(CITY))


@pytest.fixture(scope="module")
def held_out() -> mujoco.MjModel:
    return mujoco.MjModel.from_xml_path(str(HELD_OUT))


def _colliding(model: mujoco.MjModel) -> list[int]:
    return [
        gid
        for gid in range(model.ngeom)
        if int(model.geom_contype[gid]) | int(model.geom_conaffinity[gid])
    ]


def collision_signature(model: mujoco.MjModel) -> tuple[str, int]:
    """Hash every physically meaningful field of every colliding geom.

    Deliberately NOT a hash of the whole model: adding a visual geom, a texture
    or a mesh must be free, or the pin would redden on work it is not there to
    police. Deliberately NOT a hash of the XML either: the XML is where the
    change is allowed to happen; the compiled contact model is what must not.
    """

    rows = []
    for gid in _colliding(model):
        rows.append(
            {
                "name": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, gid) or "",
                "body": mujoco.mj_id2name(
                    model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[gid])
                )
                or "",
                "type": int(model.geom_type[gid]),
                "contype": int(model.geom_contype[gid]),
                "conaffinity": int(model.geom_conaffinity[gid]),
                "condim": int(model.geom_condim[gid]),
                "size": [float(v) for v in model.geom_size[gid]],
                "pos": [float(v) for v in model.geom_pos[gid]],
                "quat": [float(v) for v in model.geom_quat[gid]],
                "friction": [float(v) for v in model.geom_friction[gid]],
                "solref": [float(v) for v in model.geom_solref[gid]],
                "solimp": [float(v) for v in model.geom_solimp[gid]],
                "margin": float(model.geom_margin[gid]),
                "gap": float(model.geom_gap[gid]),
            }
        )
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest(), len(rows)


def _geom_names(model: mujoco.MjModel) -> list[str]:
    return [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, gid) or ""
        for gid in range(model.ngeom)
    ]


# ---------------------------------------------------------------------------
# 1. Physics did not move.
# ---------------------------------------------------------------------------


def test_the_city_block_collision_model_is_byte_frozen(city: mujoco.MjModel) -> None:
    signature, count = collision_signature(city)
    assert count == CITY_COLLIDING_GEOM_COUNT
    assert signature == CITY_COLLISION_SIGNATURE, (
        "the block's contact model changed. Textures and visual meshes must not "
        "touch it; if a card genuinely intends to move physics, re-pin this with "
        "the same evidence a frozen-digest re-pin needs."
    )


def test_every_geom_this_card_added_is_visually_prefixed_and_non_colliding(
    city: mujoco.MjModel,
) -> None:
    """The invariant that makes the frozen signature possible at all."""

    visual = [name for name in _geom_names(city) if name.startswith(VISUAL_PREFIX)]
    assert visual, "the textured scene should carry vis_* geoms"
    for gid in range(city.ngeom):
        name = mujoco.mj_id2name(city, mujoco.mjtObj.mjOBJ_GEOM, gid) or ""
        if not name.startswith(VISUAL_PREFIX):
            continue
        assert int(city.geom_contype[gid]) == 0, f"{name} can collide"
        assert int(city.geom_conaffinity[gid]) == 0, f"{name} can be collided with"


def test_a_visual_geom_never_contributes_mass(city: mujoco.MjModel) -> None:
    """`density="0"` is what keeps a mocap actor's body_mass unchanged.

    Without it MuJoCo derives a mesh's mass from its volume and the pedestrian
    bodies' inertial properties move, which is a physics change even though a
    mocap body is never integrated.
    """

    for gid in range(city.ngeom):
        name = mujoco.mj_id2name(city, mujoco.mjtObj.mjOBJ_GEOM, gid) or ""
        if not name.startswith(VISUAL_PREFIX):
            continue
        body = int(city.geom_bodyid[gid])
        # A body whose ONLY geoms are visual must have zero derived mass.
        siblings = [g for g in range(city.ngeom) if int(city.geom_bodyid[g]) == body]
        if all(
            (mujoco.mj_id2name(city, mujoco.mjtObj.mjOBJ_GEOM, g) or "").startswith(
                VISUAL_PREFIX
            )
            for g in siblings
        ):
            assert float(city.body_mass[body]) == 0.0, f"{name}'s body gained mass"


def inertial_signature(model: mujoco.MjModel) -> tuple[str, int]:
    rows = []
    for bid in range(model.nbody):
        rows.append(
            {
                "name": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, bid) or "",
                "mass": float(model.body_mass[bid]),
                "inertia": [float(v) for v in model.body_inertia[bid]],
                "ipos": [float(v) for v in model.body_ipos[bid]],
                "iquat": [float(v) for v in model.body_iquat[bid]],
                "pos": [float(v) for v in model.body_pos[bid]],
                "quat": [float(v) for v in model.body_quat[bid]],
            }
        )
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest(), len(rows)


def test_the_body_inertial_model_is_byte_frozen(city: mujoco.MjModel) -> None:
    signature, count = inertial_signature(city)
    assert count == CITY_BODY_COUNT
    assert signature == CITY_INERTIAL_SIGNATURE, (
        "a body's mass or inertia moved. The usual cause is a visual geom that "
        'lost its density="0".'
    )


def test_every_visual_geom_declares_zero_density() -> None:
    """The XML-level half of the same claim, so the failure names the geom.

    Read from the source rather than the compiled model because the compiled
    model only shows the *aggregate* body mass; this shows which declaration is
    missing the attribute.
    """

    for scene in (CITY, HELD_OUT):
        text = scene.read_text(encoding="utf-8")
        for block in re.findall(r"<geom\b[^>]*?/>", text, flags=re.DOTALL):
            name = re.search(r'name="([^"]+)"', block)
            if not name or not name.group(1).startswith(VISUAL_PREFIX):
                continue
            assert 'density="0"' in block, (
                f'{scene.name}: {name.group(1)} does not declare density="0"'
            )
            assert 'contype="0"' in block and 'conaffinity="0"' in block, name.group(1)


def test_the_logical_obstacle_set_is_frozen(city: mujoco.MjModel) -> None:
    """A decorative geom must never enter the obstacle namespace.

    `vis_*` cannot match `LOGICAL_OBSTACLE_PREFIXES` by construction — but a
    future edit that names a decoration `obstacle_awning` or `bench_sign` would
    slip past that check while adding something the robot brakes for. Freezing
    the resolved set catches the naming mistake the prefix rule cannot.
    """

    names = sorted(name for name in _geom_names(city) if is_logical_obstacle_name(name))
    signature = hashlib.sha256(
        json.dumps(names, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert len(names) == CITY_LOGICAL_OBSTACLE_COUNT
    assert signature == CITY_LOGICAL_OBSTACLE_SIGNATURE, (
        f"the block's logical-obstacle set changed: {names}"
    )


def test_the_person_bodies_kept_their_capsules(city: mujoco.MjModel) -> None:
    """The card's rule: the collider stays, the visual rides along.

    The capsules are hidden (MuJoCo group 4 is not drawn by the default
    mjvOption) rather than deleted, because every non-visual consumer — the
    viewer payload, the dynamic-agent channel, anything reading geom names —
    still reads them.
    """

    names = set(_geom_names(city))
    for body in [f"pedestrian_{i}" for i in range(1, 8)] + ["owner", "cyclist_1"]:
        assert f"{body}_body" in names, f"{body} lost its capsule"
        assert f"vis_{body}" in names, f"{body} has no visual mesh"
    for name in names:
        if name.endswith(("_body", "_head")) and not name.startswith(VISUAL_PREFIX):
            gid = mujoco.mj_name2id(city, mujoco.mjtObj.mjOBJ_GEOM, name)
            if gid < 0:
                continue
            assert int(city.geom_group[gid]) == 4, (
                f"{name} must sit in the un-drawn group 4, or the capsule and the "
                "human mesh render on top of each other"
            )


# ---------------------------------------------------------------------------
# 2. The visual namespace is inert to every consumer that reads geom names.
# ---------------------------------------------------------------------------


def test_the_visual_prefix_collides_with_no_consumer_prefix_table() -> None:
    """Checked against the live tables, not against a copy of them."""

    tables = {
        "sim.LOGICAL_OBSTACLE_PREFIXES": LOGICAL_OBSTACLE_PREFIXES,
        "headless_city._STATIC_OBSTACLE_PREFIXES": _STATIC_OBSTACLE_PREFIXES,
        "city_semantics.OBJECT_PREFIX_TABLE": tuple(p for p, _ in OBJECT_PREFIX_TABLE),
        "city_semantics.REGION_PREFIX_TABLE": tuple(p for p, _ in REGION_PREFIX_TABLE),
    }
    for label, prefixes in tables.items():
        for prefix in prefixes:
            assert not VISUAL_PREFIX.startswith(prefix), f"{VISUAL_PREFIX} matches {label}:{prefix}"
            assert not prefix.startswith(VISUAL_PREFIX), f"{label}:{prefix} lives in {VISUAL_PREFIX}"


def test_no_visual_geom_is_a_logical_obstacle(city: mujoco.MjModel) -> None:
    for name in _geom_names(city):
        if name.startswith(VISUAL_PREFIX):
            assert not is_logical_obstacle_name(name)


def test_the_orbit_clearance_prefixes_do_not_reach_the_visual_namespace() -> None:
    from tests.test_city_orbit_clearance import STATIC_LOGICAL_PREFIXES

    for prefix in STATIC_LOGICAL_PREFIXES:
        assert not VISUAL_PREFIX.startswith(prefix)


@pytest.mark.parametrize("scene_name", ["city_block.xml", "city_block_b.xml"])
def test_texturing_added_no_semantic_instance(scene_name: str) -> None:
    """The extraction must see exactly the classes the sidecar declares."""

    from parcel_robot.perception.city_semantics import extract_city_semantics

    model = mujoco.MjModel.from_xml_path(str(SCENES / scene_name))
    regions, objects = extract_city_semantics(model)
    ids = {str(item["id"]) for item in regions} | {str(item["id"]) for item in objects}
    assert not any(entity.startswith(VISUAL_PREFIX) for entity in ids)
    labels = {str(item["label"]) for item in regions} | {
        str(item["label"]) for item in objects
    }
    assert labels == {
        "bench",
        "building",
        "crosswalk",
        "door",
        "lamppost",
        "planter",
        "sidewalk",
        "tree",
    }


def test_the_block_still_grounds_exactly_one_door(city: mujoco.MjModel) -> None:
    """R14's invariant: the storefront art must not create rival door candidates."""

    from parcel_robot.perception.city_semantics import extract_city_semantics

    _, objects = extract_city_semantics(city)
    doors = [item for item in objects if item["label"] == "door"]
    assert [item["id"] for item in doors] == ["door_1"]


# ---------------------------------------------------------------------------
# 3. The assets exist, and are the assets that were built.
# ---------------------------------------------------------------------------

_FILE_ATTR = re.compile(r'file="([^"]+)"')


def _referenced_assets(scene: Path) -> set[Path]:
    """Every asset path the MJCF names, resolved the way MuJoCo resolves it."""

    text = scene.read_text(encoding="utf-8")
    texturedir = re.search(r'texturedir="([^"]+)"', text)
    meshdir = re.search(r'meshdir="([^"]+)"', text)
    out: set[Path] = set()
    for block in re.findall(r"<texture\b[^>]*>", text):
        match = _FILE_ATTR.search(block)
        if match and texturedir:
            out.add((scene.parent / texturedir.group(1) / match.group(1)).resolve())
    for block in re.findall(r"<mesh\b[^>]*?/>", text, flags=re.DOTALL):
        match = _FILE_ATTR.search(block)
        if match and meshdir:
            out.add((scene.parent / meshdir.group(1) / match.group(1)).resolve())
    return out


@pytest.mark.parametrize("scene_name", ["city_block.xml", "city_block_b.xml"])
def test_every_texture_and_mesh_the_scene_references_exists(scene_name: str) -> None:
    referenced = _referenced_assets(SCENES / scene_name)
    assert referenced, f"{scene_name} references no external asset — did the regex rot?"
    missing = sorted(str(path) for path in referenced if not path.is_file())
    assert not missing, f"{scene_name} references assets that do not exist: {missing}"


@pytest.mark.parametrize("scene_name", ["city_block.xml", "city_block_b.xml"])
def test_referenced_assets_live_under_the_scenes_asset_tree(scene_name: str) -> None:
    """A path that escapes `scenes/assets` would not ship in the wheel."""

    for path in _referenced_assets(SCENES / scene_name):
        if "unitree_mujoco" in path.parts:
            continue  # the Go2's own meshes, shipped by third_party
        assert path.is_relative_to(ASSETS), f"{path} is outside {ASSETS}"


def test_every_built_asset_matches_its_recorded_digest() -> None:
    """A hand-edited PNG is a red build.

    `assets/` is a build product of `scratchpad/w1/build_assets.py` over CC0
    sources. Recording the digests is what makes "regenerate, never edit" an
    enforceable rule instead of a comment.
    """

    manifest = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert manifest["files"], "PROVENANCE.json records no files"
    for relpath, entry in sorted(manifest["files"].items()):
        path = ASSETS / relpath
        assert path.is_file(), f"{relpath} is recorded but missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == entry["sha256"], f"{relpath} does not match its recorded digest"
        assert path.stat().st_size == entry["bytes"]


def test_no_asset_file_is_unrecorded() -> None:
    manifest = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    on_disk = {
        path.relative_to(ASSETS).as_posix()
        for path in ASSETS.rglob("*")
        if path.is_file() and path.name != PROVENANCE.name
    }
    assert on_disk == set(manifest["files"]), (
        "an asset appeared or vanished without the provenance record following it"
    )


def test_every_upstream_source_is_cc0_with_an_attributable_author() -> None:
    manifest = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert manifest["sources"], "no upstream sources recorded"
    for row in manifest["sources"]:
        licence = row.get("license") or row.get("licence")
        assert licence == "CC0", f"{row.get('asset_id')} is not recorded as CC0"
        assert row.get("authors"), f"{row.get('asset_id')} has no attributable author"
        assert str(row.get("source", "")).startswith("https://"), row.get("asset_id")
        assert row.get("md5"), f"{row.get('asset_id')} has no upstream digest"


def test_the_packaged_wheel_would_carry_the_assets() -> None:
    """Without the package-data glob a wheel ships an uncompilable scene."""

    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    for glob in ("scenes/assets/textures/*.png", "scenes/assets/meshes/*.obj",
                 "scenes/assets/*.json"):
        assert glob in pyproject, f"pyproject package-data is missing {glob}"


# ---------------------------------------------------------------------------
# 4. The held-out scene is a real variant, not a recolour.
# ---------------------------------------------------------------------------


def test_the_held_out_scene_shares_no_texture_with_the_development_scene() -> None:
    """A variant that reuses the same materials is not a generalization venue.

    The two scenes may share *meshes* (the same nine bodies are people in both,
    and a detector that only works on one silhouette is exactly what >= 3
    variants is meant to prevent). They must not share the SURFACE textures.
    """

    def textures(scene: Path) -> set[str]:
        text = scene.read_text(encoding="utf-8")
        return {
            _FILE_ATTR.search(block).group(1)
            for block in re.findall(r"<texture\b[^>]*>", text)
            if _FILE_ATTR.search(block)
        }

    a, b = textures(CITY), textures(HELD_OUT)
    assert a and b
    shared = a & b
    # crosswalk paint, curb concrete, bark, canopy and grass are the same
    # material in any city; the FACADES, ROAD, SIDEWALK, BENCH, DOOR and every
    # STOREFRONT must differ, because those are what a facade detector keys on.
    must_differ = {"facade", "road_", "sidewalk_", "bench_", "door_", "storefront_"}
    for name in shared:
        assert not any(token in name for token in must_differ), (
            f"{name} is used by both the development and the held-out scene"
        )
    assert len(b - a) >= 6, "the held-out scene barely differs from the development one"


def test_the_held_out_scene_has_a_different_layout(
    city: mujoco.MjModel, held_out: mujoco.MjModel
) -> None:
    from parcel_robot.perception.city_semantics import extract_city_semantics

    a_regions, a_objects = extract_city_semantics(city)
    b_regions, b_objects = extract_city_semantics(held_out)
    a_pos = {str(o["id"]): tuple(round(float(v), 3) for v in o["position"][:2]) for o in a_objects}
    b_pos = {str(o["id"]): tuple(round(float(v), 3) for v in o["position"][:2]) for o in b_objects}
    shared = set(a_pos) & set(b_pos)
    assert shared, "the two scenes should name some of the same entity ids"
    assert not any(a_pos[k] == b_pos[k] for k in shared), (
        "at least one landmark stands in exactly the same place in both scenes"
    )
    a_polys = {str(r["id"]): r["polygon"] for r in a_regions}
    b_polys = {str(r["id"]): r["polygon"] for r in b_regions}
    assert a_polys["crosswalk"] != b_polys["crosswalk"]
    assert a_polys["sidewalk"] != b_polys["sidewalk"]


def test_every_visual_geom_in_the_held_out_scene_is_inert_too(
    held_out: mujoco.MjModel,
) -> None:
    for gid in range(held_out.ngeom):
        name = mujoco.mj_id2name(held_out, mujoco.mjtObj.mjOBJ_GEOM, gid) or ""
        if not name.startswith(VISUAL_PREFIX):
            continue
        assert int(held_out.geom_contype[gid]) == 0
        assert int(held_out.geom_conaffinity[gid]) == 0
        assert not is_logical_obstacle_name(name)
