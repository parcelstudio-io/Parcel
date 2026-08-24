"""Card C-2 — the dog's own map. Offline-first properties, every one of them.

Every property the card names is driven from a fixture detection stream rather
than from a live stack: the real 16-frame stream C-1 published from the textured
world (``tests/data/c2_online_map_frames.json``) plus hand-built cases for the
things a real patrol cannot conveniently produce — a poster, a decal, an
absent-on-revisit place, a stale embedding space.

The two red-team decoys live here as fixtures, and the reason is recorded in
``C2_STATUS.md``: putting them in ``city_block.xml`` moves the scene sha, which
moves a frozen digest sentinel, which is an owner-authorized re-pin under the
R14 protocol and none of those files is in C-2's OWNS. Fixtures exercise the
gates; the scene edit is written up as a one-act follow-up.
"""

from __future__ import annotations

import ast
import json
import math
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from parcel_robot.online_map.entries import (
    CHANNEL_DETECTOR_LABEL,
    CHANNEL_EMBEDDING,
    CHANNEL_TEXT_NAME,
    ENV_MAP_PATH,
    NAME_PROMOTION_VISITS,
    STATUS_ACTIVE,
    STATUS_DECAYED,
    EmbeddingStamp,
    MapObservation,
    WriterProvenance,
)
from parcel_robot.online_map.hygiene import (
    NOTE_OK,
    NOTE_PLANAR,
    NOTE_RELIEF_UNVERIFIED,
    NOTE_TOO_SMALL,
    NOTE_VOLATILE,
    is_volatile_label,
    metric_extents,
    relief_from_depth_patch,
    screen_observation,
)
from parcel_robot.online_map.ingest import observations_from_frame
from parcel_robot.online_map.online_map import (
    EMBEDDING_RERANKED,
    EMBEDDING_UNAVAILABLE_VERSION,
    GROUND_SOURCE_TRAVERSAL,
    GROUND_SOURCE_UNMEASURED,
    OnlineSemanticMap,
)
from parcel_robot.online_map.store import MapStoreRefused, OnlineMapStore, resolve_map_store_path

FIXTURE = Path(__file__).parent / "data" / "c2_online_map_frames.json"

PROV = WriterProvenance(
    session_id="c2-test",
    seat="in_loop_query",
    detector_name="owlv2-b16-int8",
    scene_id="city_block",
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def obs(
    label: str = "lamppost",
    *,
    x: float = 3.0,
    y: float = 1.0,
    z: float = 1.2,
    score: float = 0.4,
    w: float = 0.2,
    h: float = 3.0,
    frame_id: str = "f1",
    visit_id: str = "v1",
    wall_s: float = 100.0,
    pixels: int = 800,
    embedding=None,
    stamp=None,
    relief_m=None,
    relief_samples: int = 0,
) -> MapObservation:
    return MapObservation(
        label=label,
        score=score,
        surface_x=x,
        surface_y=y,
        surface_z=z,
        range_m=4.0,
        bearing_rad=0.0,
        depth_m=4.0,
        extent_w_m=w,
        extent_h_m=h,
        inlier_pixels=pixels,
        frame_id=frame_id,
        visit_id=visit_id,
        observed_wall_s=wall_s,
        robot_x=0.0,
        robot_y=0.0,
        provenance=PROV,
        embedding=embedding,
        embedding_stamp=stamp,
        relief_m=relief_m,
        relief_samples=relief_samples,
    )


def fresh_map(**kwargs) -> OnlineSemanticMap:
    return OnlineSemanticMap(provenance=PROV, **kwargs)


class _Rec:
    """Duck-typed CameraDetectionRecord, as the ingest seam consumes it."""

    def __init__(self, data: dict) -> None:
        self.__dict__.update(data)
        self.box = tuple(float(v) for v in data["box"])


class _Frame:
    def __init__(self, data: dict) -> None:
        self.__dict__.update(data)
        self.detections = tuple(_Rec(d) for d in data["detections"])
        self.queries = tuple(data.get("queries", ()))


def real_frames() -> tuple[_Frame, ...]:
    payload = json.loads(FIXTURE.read_text())
    return tuple(_Frame(f) for f in payload["frames"])


# --------------------------------------------------------------------------
# 1. Entry validation — a rumour with coordinates is not evidence.
# --------------------------------------------------------------------------


def test_an_embedding_without_a_stamp_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown space"):
        obs(embedding=(0.1, 0.2, 0.3))


def test_an_embedding_that_disagrees_with_its_stamped_dim_is_refused() -> None:
    stamp = EmbeddingStamp("siglip2-b16", "r1", 4, "224-center")
    with pytest.raises(ValueError, match="stamped dim"):
        obs(embedding=(0.1, 0.2, 0.3), stamp=stamp)


def test_relief_without_samples_is_a_claim_without_a_measurement() -> None:
    with pytest.raises(ValueError, match="without a measurement"):
        obs(relief_m=0.4, relief_samples=0)


def test_embedding_spaces_compare_only_within_one_space_key() -> None:
    a = EmbeddingStamp("siglip2-b16", "r1", 8, "224-center")
    b = EmbeddingStamp("siglip2-b16", "r2", 8, "224-center")
    c = EmbeddingStamp("siglip2-b16", "r1", 8, "224-center")
    assert a.compatible_with(c)
    assert not a.compatible_with(b)
    assert a.space_key != b.space_key


# --------------------------------------------------------------------------
# 2. Hygiene gate (a) — volatile classes are never places.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label", ["person", "a person", "Person", "pedestrian", "car", "dog", "cyclist"]
)
def test_volatile_labels_are_recognised(label: str) -> None:
    assert is_volatile_label(label)


@pytest.mark.parametrize(
    "label", ["bike rack", "person crossing sign", "bus stop", "lamppost", "tree"]
)
def test_fixed_things_that_merely_contain_a_volatile_word_are_not_volatile(
    label: str,
) -> None:
    assert not is_volatile_label(label)


def test_a_person_is_observed_counted_and_never_persisted() -> None:
    m = fresh_map()
    m.note_frame(("person", "lamppost"))
    outcome = m.observe(obs("person", w=0.6, h=1.8))
    assert outcome.observed is True
    assert outcome.persisted is False
    assert outcome.hygiene.note == NOTE_VOLATILE
    assert len(m) == 0
    assert m.stats()["refused_volatile"] == 1
    assert m.stats()["observations_seen"] == 1


def test_the_poster_decoy_cannot_enter_the_map_as_a_person() -> None:
    """RED-TEAM DECOY 1: a photorealistic person poster.

    It fires the detector, it is re-observed every patrol so its evidence
    strengthens, and it sits above navigable ground. Gate (a) refuses it
    without needing a single depth sample, which is the property that matters:
    the defence cannot be disabled by the poster being well-lit.
    """

    m = fresh_map()
    for i in range(12):
        m.note_frame(("person",))
        m.observe(obs("person", w=0.55, h=1.75, frame_id=f"f{i}", visit_id=f"v{i}"))
    assert len(m) == 0
    assert m.known_places() == ()
    assert m.resolve("person").candidates == ()


# --------------------------------------------------------------------------
# 3. Hygiene gate (b) — metric size and depth planarity.
# --------------------------------------------------------------------------


def test_metric_extents_back_project_the_box_at_depth() -> None:
    w, h = metric_extents((100.0, 100.0, 200.0, 400.0), 4.0, fx=644.0, fy=644.0)
    assert w == pytest.approx(100.0 * 4.0 / 644.0)
    assert h == pytest.approx(300.0 * 4.0 / 644.0)


def test_the_decal_decoy_cannot_forge_a_storefront() -> None:
    """RED-TEAM DECOY 2: a scene-text decal reading "coffee shop".

    A 0.45 m x 0.25 m painted sign is a perfect label match and a perfect
    location — and it is not a shop. Only the metric size knows that.
    """

    verdict = screen_observation(
        label="coffee shop",
        extent_w_m=0.45,
        extent_h_m=0.25,
        relief_m=None,
        relief_samples=0,
    )
    assert verdict.admitted is False
    assert verdict.note == NOTE_TOO_SMALL
    assert verdict.prior_key == "coffee shop"


def test_the_decal_decoy_is_refused_by_the_map_itself() -> None:
    m = fresh_map()
    for i in range(10):
        m.note_frame(("coffee shop",))
        m.observe(obs("coffee shop", w=0.45, h=0.25, frame_id=f"f{i}", visit_id=f"v{i}"))
    assert len(m) == 0
    assert m.stats()["refused_hygiene"] == 10
    assert m.resolve("coffee shop").candidates == ()


def test_a_planar_thing_is_refused_when_relief_was_actually_measured() -> None:
    verdict = screen_observation(
        label="tree", extent_w_m=1.5, extent_h_m=4.0, relief_m=0.004, relief_samples=900
    )
    assert verdict.admitted is False
    assert verdict.note == NOTE_PLANAR


def test_a_solid_thing_passes_relief_and_is_marked_verified() -> None:
    verdict = screen_observation(
        label="tree", extent_w_m=1.5, extent_h_m=4.0, relief_m=0.9, relief_samples=900
    )
    assert verdict.admitted is True
    assert verdict.note == NOTE_OK
    assert verdict.relief_verified is True


def test_absent_relief_admits_on_size_and_says_the_claim_was_not_checked() -> None:
    """The honest half. C-1's record carries no depth returns, so the map must
    not imply a planarity check that never ran."""

    verdict = screen_observation(
        label="tree", extent_w_m=1.5, extent_h_m=4.0, relief_m=None, relief_samples=0
    )
    assert verdict.admitted is True
    assert verdict.note == NOTE_RELIEF_UNVERIFIED
    assert verdict.relief_verified is False


def test_relief_from_a_planar_patch_is_near_zero_and_from_a_curved_one_is_not() -> None:
    flat = [[3.0] * 12 for _ in range(12)]
    flat_relief, flat_n = relief_from_depth_patch(flat)
    assert flat_n == 144
    assert flat_relief == pytest.approx(0.0, abs=1e-9)

    curved = [
        [3.0 + 0.5 * math.sin(math.pi * col / 11) for col in range(12)]
        for _ in range(12)
    ]
    curved_relief, curved_n = relief_from_depth_patch(curved)
    assert curved_n == 144
    assert curved_relief > 0.2


def test_relief_refuses_to_answer_from_too_few_samples() -> None:
    relief, n = relief_from_depth_patch([[3.0, 3.1, 3.2]])
    assert relief is None
    assert n == 3


def test_sigma_range_is_not_used_as_a_planarity_signal() -> None:
    """The trap this module was nearly built on, pinned so nobody re-enters it.

    ``CameraDetectionRecord.sigma_range_m`` is a metre-valued depth uncertainty
    sitting right on the record, and it is ``coeff * range**2`` — a pure
    function of range with zero planarity information. If a future edit wires
    it into the hygiene path this test goes red.
    """

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "parcel_robot"
        / "online_map"
        / "hygiene.py"
    ).read_text()
    # It may be NAMED (the docstring explains the trap); it may not be READ.
    assert "record.sigma_range_m" not in source
    assert "sigma_range_m=" not in source


# --------------------------------------------------------------------------
# 4. Growth and fusion.
# --------------------------------------------------------------------------


def test_reobservation_strengthens_and_does_not_duplicate() -> None:
    m = fresh_map()
    for i in range(8):
        m.note_frame(("lamppost",))
        m.observe(obs(x=3.0 + 0.01 * i, y=1.0, frame_id=f"f{i}", visit_id="v1"))
    assert len(m) == 1
    entry = m.entries()[0]
    assert entry.evidence_frames == 8
    assert entry.detection_count == 8
    assert entry.label_support == 8
    assert entry.label_purity == pytest.approx(1.0)


def test_two_places_of_one_class_beyond_the_fuse_radius_stay_two_places() -> None:
    m = fresh_map()
    m.note_frame(("lamppost",))
    m.observe(obs(x=0.0, y=0.0))
    m.note_frame(("lamppost",))
    m.observe(obs(x=12.0, y=0.0, frame_id="f2"))
    assert len(m) == 2


def test_position_is_the_median_of_its_surface_points() -> None:
    m = fresh_map()
    for i, x in enumerate([3.0, 3.1, 3.2, 3.3, 9.0]):
        m.note_frame(("lamppost",))
        # keep them inside the fuse radius of the running median
        m.observe(obs(x=min(x, 3.4), frame_id=f"f{i}"))
    entry = m.entries()[0]
    assert entry.surface_x == pytest.approx(3.2, abs=0.05)


# --------------------------------------------------------------------------
# 5. Best-view embeddings — REVISION 2.
# --------------------------------------------------------------------------


STAMP = EmbeddingStamp("siglip2-b16", "r1", 4, "224-center")


def test_the_stored_embedding_is_the_best_view_and_never_a_blend() -> None:
    m = fresh_map()
    poor = (1.0, 0.0, 0.0, 0.0)
    best = (0.0, 1.0, 0.0, 0.0)
    m.note_frame(("lamppost",))
    m.observe(obs(embedding=poor, stamp=STAMP, pixels=100, score=0.3))
    m.note_frame(("lamppost",))
    m.observe(obs(embedding=best, stamp=STAMP, pixels=9000, score=0.9, frame_id="f2"))
    m.note_frame(("lamppost",))
    m.observe(obs(embedding=poor, stamp=STAMP, pixels=50, score=0.2, frame_id="f3"))

    entry = m.entries()[0]
    # Byte-exactly one of the observed views. An average of these three would be
    # a valid-looking vector describing no view that ever existed.
    assert entry.embedding == best
    assert entry.embedding in (poor, best)


def test_a_worse_view_never_displaces_a_better_one() -> None:
    m = fresh_map()
    good = (0.0, 1.0, 0.0, 0.0)
    m.note_frame(("lamppost",))
    m.observe(obs(embedding=good, stamp=STAMP, pixels=9000, score=0.9))
    m.note_frame(("lamppost",))
    m.observe(obs(embedding=(1.0, 0.0, 0.0, 0.0), stamp=STAMP, pixels=10, score=0.1,
                  frame_id="f2"))
    assert m.entries()[0].embedding == good


# --------------------------------------------------------------------------
# 6. Decay = quarantine, and nothing is ever deleted.
# --------------------------------------------------------------------------


def _seed_two_places(m: OnlineSemanticMap) -> None:
    for i in range(8):
        m.note_frame(("lamppost", "tree"))
        m.note_pose(0.5 * i, 0.0)
        m.observe(obs("lamppost", x=3.0, y=1.0, frame_id=f"a{i}", visit_id="v0"))
        m.observe(obs("tree", x=-4.0, y=2.0, w=1.5, h=5.0, frame_id=f"b{i}",
                      visit_id="v0"))


def test_absence_marks_and_never_deletes() -> None:
    m = fresh_map()
    _seed_two_places(m)
    assert len(m) == 2

    path = [(x * 0.5, 0.0) for x in range(10)]
    for visit in range(1, 4):
        m.note_frame(("lamppost", "tree"))
        m.observe(obs("lamppost", x=3.0, y=1.0, frame_id=f"c{visit}",
                      visit_id=f"v{visit}"))
        newly = m.close_visit(f"v{visit}", wall_s=200.0 + visit, robot_path=path)

    assert newly == (m.entries()[1].entry_id,) or newly
    # Entry count is MONOTONE: the tree is still here, with its whole history.
    assert len(m) == 2
    tree = next(e for e in m.entries() if e.label == "tree")
    assert tree.status == STATUS_DECAYED
    assert any(row[1] == "decayed" for row in tree.history)
    assert tree.evidence_frames == 8  # its evidence was not erased either


def test_a_decayed_entry_is_excluded_from_retrieval_not_merely_annotated() -> None:
    m = fresh_map()
    _seed_two_places(m)
    path = [(x * 0.5, 0.0) for x in range(10)]
    for visit in range(1, 4):
        m.note_frame(("lamppost", "tree"))
        m.observe(obs("lamppost", frame_id=f"c{visit}", visit_id=f"v{visit}"))
        m.close_visit(f"v{visit}", wall_s=200.0 + visit, robot_path=path)

    assert m.resolve("tree").candidates == ()
    assert "tree" not in m.known_places()
    assert all(r["label"] != "tree" for r in m.around_me(0.0, 0.0, 0.0, radius_m=50.0))
    # ...and still visible to an auditor.
    assert any(e.label == "tree" for e in m.entries())


def test_a_place_never_visited_is_not_decayed_for_being_absent() -> None:
    """A robot that never went down that street has not observed an absence."""

    m = fresh_map()
    _seed_two_places(m)
    far_path = [(200.0, 200.0)]
    for visit in range(1, 6):
        m.close_visit(f"v{visit}", wall_s=300.0 + visit, robot_path=far_path)
    assert all(e.status == STATUS_ACTIVE for e in m.entries())


def test_a_revisited_place_revives_and_keeps_its_decay_in_history() -> None:
    m = fresh_map()
    _seed_two_places(m)
    path = [(x * 0.5, 0.0) for x in range(10)]
    for visit in range(1, 4):
        m.close_visit(f"v{visit}", wall_s=200.0 + visit, robot_path=path)
    tree = next(e for e in m.entries() if e.label == "tree")
    assert tree.status == STATUS_DECAYED

    m.note_frame(("tree",))
    m.observe(obs("tree", x=-4.0, y=2.0, w=1.5, h=5.0, frame_id="z", visit_id="v9"))
    tree = next(e for e in m.entries() if e.label == "tree")
    assert tree.status == STATUS_ACTIVE
    assert [row[1] for row in tree.history].count("decayed") == 1
    assert any(row[1] == "revived" for row in tree.history)


def test_the_package_contains_no_delete_path() -> None:
    """Structural. 'Nothing is ever silently deleted' is a property of the code,
    not of this run's inputs."""

    root = Path(__file__).resolve().parents[1] / "src" / "parcel_robot" / "online_map"
    for path in sorted(root.glob("*.py")):
        source = path.read_text()
        assert "DELETE FROM" not in source.upper(), path
        assert "DROP TABLE" not in source.upper(), path
        assert "del self._entries" not in source, path
        assert ".pop(" not in source or path.name == "entries.py", path


# --------------------------------------------------------------------------
# 7. Persistence and isolation — R27 class.
# --------------------------------------------------------------------------


def test_no_declaration_means_no_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_MAP_PATH, raising=False)
    with pytest.raises(MapStoreRefused, match="nothing declared"):
        resolve_map_store_path(env={})


def test_a_relative_map_path_is_refused() -> None:
    with pytest.raises(MapStoreRefused, match="RELATIVE"):
        resolve_map_store_path("map.sqlite3")


def test_the_owner_conversation_store_is_refused_by_name(tmp_path: Path) -> None:
    # The filename is read from the authority rather than typed here: the
    # owner-store isolation gate treats a hardcoded copy as the next pollution
    # vector, and it is right to — it caught this very test.
    from parcel_robot.memory_path import OWNER_STORE_NAME

    with pytest.raises(MapStoreRefused, match="conversation store"):
        resolve_map_store_path(tmp_path / OWNER_STORE_NAME)


def test_the_owner_conversation_store_is_refused_by_identity() -> None:
    from parcel_robot.memory_path import owner_store_paths

    for owner in owner_store_paths():
        with pytest.raises(MapStoreRefused, match="conversation store"):
            resolve_map_store_path(owner)


def test_in_memory_is_allowed() -> None:
    assert resolve_map_store_path(":memory:") == ":memory:"


def test_the_env_override_is_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "dogmap.sqlite3"
    monkeypatch.setenv(ENV_MAP_PATH, str(target))
    assert resolve_map_store_path() == str(target.resolve())


def test_a_map_reloads_entry_for_entry_with_its_provenance(tmp_path: Path) -> None:
    path = tmp_path / "dogmap.sqlite3"
    store = OnlineMapStore(path)
    m = OnlineSemanticMap(store, provenance=PROV)
    for i in range(8):
        m.note_frame(("lamppost",))
        m.observe(obs(frame_id=f"f{i}", embedding=(0.0, 1.0, 0.0, 0.0), stamp=STAMP))
    written = m.persist()
    store.close()
    assert written == 1

    store2 = OnlineMapStore(path)
    m2 = OnlineSemanticMap(store2, provenance=PROV)
    assert len(m2) == 1
    before, after = m.entries()[0], m2.entries()[0]
    assert before.as_dict() == after.as_dict()
    assert after.provenance.session_id == "c2-test"
    assert after.provenance.seat == "in_loop_query"
    assert after.provenance.detector_name == "owlv2-b16-int8"
    assert after.embedding_stamp is not None
    assert after.embedding_stamp.space_key == STAMP.space_key
    store2.close()


def test_a_store_written_by_another_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "dogmap.sqlite3"
    OnlineMapStore(path).close()
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("UPDATE map_meta SET value = 'parcel.online_map.v0' "
                     "WHERE key = 'schema'")
    conn.close()
    with pytest.raises(MapStoreRefused, match="schema"):
        OnlineMapStore(path)


def test_reload_survives_a_fresh_interpreter(tmp_path: Path) -> None:
    """The card's claim in its literal form: a NEW process knows the lamppost."""

    path = tmp_path / "dogmap.sqlite3"
    store = OnlineMapStore(path)
    m = OnlineSemanticMap(store, provenance=PROV)
    for i in range(8):
        m.note_frame(("lamppost",))
        m.note_pose(0.3 * i, 0.0)
        m.observe(obs(frame_id=f"f{i}"))
    m.persist()
    store.close()

    program = (
        "import json;"
        "from parcel_robot.online_map.entries import WriterProvenance;"
        "from parcel_robot.online_map.online_map import OnlineSemanticMap;"
        "from parcel_robot.online_map.store import OnlineMapStore;"
        f"s=OnlineMapStore({str(path)!r});"
        "p=WriterProvenance(session_id='next-day', seat='in_loop_query',"
        " detector_name='owlv2-b16-int8', scene_id='city_block');"
        "m=OnlineSemanticMap(s, provenance=p);"
        "print(json.dumps({'n': len(m), 'labels': [e.label for e in m.entries()],"
        " 'frames': m.entries()[0].evidence_frames,"
        " 'writer': m.entries()[0].provenance.session_id}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert payload["n"] == 1
    assert payload["labels"] == ["lamppost"]
    assert payload["frames"] == 8
    # The entry keeps the provenance of the session that WROTE it, not of the
    # session that read it back.
    assert payload["writer"] == "c2-test"


# --------------------------------------------------------------------------
# 8. Query API — label-primary, PG-3 always consulted.
# --------------------------------------------------------------------------


def test_a_query_with_no_label_match_produces_no_candidates_and_a_verdict() -> None:
    m = fresh_map()
    _seed_two_places(m)
    result = m.resolve("fire hydrant")
    assert result.candidates == ()
    assert result.admitted is False
    assert result.verdict.reason
    assert result.channels_used == ()


def test_an_unasked_term_is_refused_because_nobody_asked() -> None:
    """Not asking is not evidence of absence — and it is not evidence of
    presence either. The refusal names the right reason."""

    m = fresh_map()
    _seed_two_places(m)
    result = m.resolve("mailbox")
    assert result.diagnostics["asked"] is False
    assert result.verdict.reason == "no_detector_support"


def test_every_resolve_carries_a_pg3_verdict_including_admissions() -> None:
    m = fresh_map()
    _seed_two_places(m)
    for query in ("lamppost", "tree", "fire hydrant", ""):
        result = m.resolve(query)
        assert result.verdict is not None
        assert isinstance(result.verdict.admitted, bool)
        assert result.verdict.reason


def test_the_label_channel_is_what_produces_candidates() -> None:
    m = fresh_map()
    _seed_two_places(m)
    result = m.resolve("lamppost")
    assert result.candidates
    assert result.channels_used[0] == CHANNEL_DETECTOR_LABEL
    assert result.best is not None
    assert result.best.label == "lamppost"


def test_an_unpromoted_vlm_name_is_not_retrievable_and_is_not_vocabulary() -> None:
    m = fresh_map()
    _seed_two_places(m)
    entry_id = next(e.entry_id for e in m.entries() if e.label == "tree")
    name = m.propose_name(entry_id, "oak by the crossing", visit_id="v0", wall_s=1.0)
    assert name.admissible is False
    assert "oak by the crossing" not in m.known_places()
    assert m.resolve("oak").candidates == ()


def test_k_independent_visits_promote_a_name_into_the_text_channel() -> None:
    m = fresh_map()
    _seed_two_places(m)
    entry_id = next(e.entry_id for e in m.entries() if e.label == "tree")
    for visit in range(NAME_PROMOTION_VISITS):
        name = m.propose_name(entry_id, "oakwood", visit_id=f"visit-{visit}",
                              wall_s=float(visit))
    assert name.admissible is True
    assert "oakwood" in m.known_places()
    result = m.resolve("oakwood")
    assert result.candidates
    assert CHANNEL_TEXT_NAME in result.channels_used


def test_the_same_visit_repeated_does_not_promote_a_name() -> None:
    """Three frames of one stare is one visit. A VLM that is wrong about an
    object is reliably wrong about it from the same viewpoint."""

    m = fresh_map()
    _seed_two_places(m)
    entry_id = next(e.entry_id for e in m.entries() if e.label == "tree")
    for _ in range(6):
        name = m.propose_name(entry_id, "oakwood", visit_id="one-visit", wall_s=1.0)
    assert name.visits == 1
    assert name.admissible is False
    assert "oakwood" not in m.known_places()


# --------------------------------------------------------------------------
# 9. The embedding channel can re-rank and can never introduce.
# --------------------------------------------------------------------------


def test_the_embedding_channel_returns_a_permutation_of_the_same_candidates() -> None:
    m = fresh_map()
    for i in range(8):
        m.note_frame(("lamppost",))
        m.observe(obs(x=3.0, y=1.0, frame_id=f"a{i}",
                      embedding=(1.0, 0.0, 0.0, 0.0), stamp=STAMP, pixels=900))
        m.observe(obs(x=20.0, y=1.0, frame_id=f"b{i}",
                      embedding=(0.0, 1.0, 0.0, 0.0), stamp=STAMP, pixels=900))

    plain = m.resolve("lamppost")
    ranked = m.resolve("lamppost", query_embedding=(0.0, 1.0, 0.0, 0.0),
                       query_stamp=STAMP)
    assert ranked.embedding_status == EMBEDDING_RERANKED
    assert CHANNEL_EMBEDDING in ranked.channels_used
    assert {c.entry_id for c in ranked.candidates} == {c.entry_id for c in plain.candidates}
    assert ranked.best is not None
    assert ranked.best.x == pytest.approx(20.0, abs=0.1)


def test_a_version_mismatch_reports_unavailable_and_never_cross_space_cosines() -> None:
    m = fresh_map()
    for i in range(8):
        m.note_frame(("lamppost",))
        m.observe(obs(x=3.0, frame_id=f"a{i}", embedding=(1.0, 0.0, 0.0, 0.0),
                      stamp=STAMP, pixels=900))
    other = EmbeddingStamp("siglip2-b16", "r2-retrained", 4, "224-center")
    result = m.resolve("lamppost", query_embedding=(0.0, 1.0, 0.0, 0.0),
                       query_stamp=other)
    assert result.embedding_status == EMBEDDING_UNAVAILABLE_VERSION
    assert CHANNEL_EMBEDDING not in result.channels_used
    # It fell back to the label channel rather than refusing or guessing.
    assert result.candidates
    assert all(c.similarity is None for c in result.candidates)


def test_the_rerank_function_cannot_see_the_entry_table_as_a_search_space() -> None:
    """Structural guarantee behind 'a channel that cannot add a candidate
    cannot hallucinate a place'."""

    from parcel_robot.online_map.online_map import _rerank_by_embedding

    m = fresh_map()
    _seed_two_places(m)
    out, status = _rerank_by_embedding((), m._entries, (1.0, 0.0, 0.0, 0.0), STAMP)
    assert out == ()
    assert status == "unused"


# --------------------------------------------------------------------------
# 10. Navigability is measured, never assumed.
# --------------------------------------------------------------------------


def test_navigability_is_unmeasured_until_the_robot_has_walked() -> None:
    m = fresh_map()
    m.note_frame(("lamppost",))
    m.observe(obs())
    fraction, source = m.navigability(m.entries()[0])
    assert fraction == 0.0
    assert source == GROUND_SOURCE_UNMEASURED


def test_walking_around_a_place_is_what_licenses_its_navigability() -> None:
    m = fresh_map()
    m.note_frame(("lamppost",))
    m.observe(obs(x=3.0, y=1.0))
    for step in range(24):
        angle = 2.0 * math.pi * step / 24
        m.note_pose(3.0 + 1.6 * math.cos(angle), 1.0 + 1.6 * math.sin(angle))
    fraction, source = m.navigability(m.entries()[0])
    assert source == GROUND_SOURCE_TRAVERSAL
    assert fraction == pytest.approx(1.0)


def test_the_pose_history_is_bounded_and_decimated() -> None:
    m = fresh_map()
    for _ in range(500):
        m.note_pose(1.0, 1.0)
    assert m.path_length == 1


# --------------------------------------------------------------------------
# 11. R18 / R20 consumers.
# --------------------------------------------------------------------------


def test_around_me_answers_by_kind_and_bearing() -> None:
    m = fresh_map()
    _seed_two_places(m)
    rows = m.around_me(0.0, 0.0, 0.0, radius_m=20.0)
    assert {r["label"] for r in rows} == {"lamppost", "tree"}
    lamp = next(r for r in rows if r["label"] == "lamppost")
    assert lamp["distance_m"] == pytest.approx(math.hypot(3.0, 1.0), abs=0.05)
    assert lamp["bearing_rad"] == pytest.approx(math.atan2(1.0, 3.0), abs=0.05)


def test_the_vocabulary_is_learned_from_the_map_not_from_a_prompt_list() -> None:
    m = fresh_map()
    _seed_two_places(m)
    assert set(m.known_places()) == {"lamppost", "tree"}


# --------------------------------------------------------------------------
# 12. route_memory integration, through its PUBLIC api only.
# --------------------------------------------------------------------------


def test_entries_bind_to_the_existing_place_graph_without_editing_it() -> None:
    from parcel_robot.pose import Frame, PoseEstimate
    from parcel_robot.route_memory.place_graph import RoutePlaceGraph

    graph = RoutePlaceGraph()
    for i in range(6):
        graph.record_visit(
            PoseEstimate(
                x=float(i), y=0.0, yaw=0.0, frame=Frame.MAP,
                stamp_monotonic_s=float(i),
            ),
            semantic_labels=(),
            timestamp_tick=i,
        )
    m = fresh_map()
    _seed_two_places(m)
    bound = m.bind_place_graph(graph)
    assert bound == len(m)
    assert all(e.place_graph_index is not None for e in m.entries())


def test_the_map_supplies_labels_through_the_graphs_own_parameter() -> None:
    m = fresh_map()
    _seed_two_places(m)
    assert set(m.semantic_labels_near(3.0, 1.0, radius_m=2.0)) == {"lamppost"}
    assert set(m.semantic_labels_near(0.0, 0.0, radius_m=50.0)) == {"lamppost", "tree"}


def test_route_memory_is_bound_to_never_forked_by_this_card() -> None:
    """The smallest honest touch turned out to be no touch at all.

    This was a ``git diff --name-only HEAD -- src/parcel_robot/route_memory``
    emptiness pin. It stopped measuring what it meant, the same way its sibling
    in ``test_c3_cutover.py`` did: a working-tree diff is a claim about whoever
    runs the suite, it goes vacuously green the moment the change is committed,
    and ANY later card chartered to touch ``route_memory/`` reddens it with
    nothing about C-2 having changed. Card DEC-IG-2 (barrel thinning) was that
    later card.

    Replaced by the property it stood in for, which is strictly stronger than
    "nobody has run git yet": C-2's own package binds to P-4's place graph
    through the graph object it is HANDED, and re-declares none of P-4's types
    and imports none of P-4's modules.
    """

    root = Path(__file__).resolve().parents[1]
    package = root / "src" / "parcel_robot" / "online_map"
    forbidden_declarations = (
        "class RouteKeyframe",
        "class RoutePath",
        "class RouteMemoryStore",
        "class RoutePlaceGraph",
        "class PlaceEdge",
    )
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            if module and "route_memory" in module:
                offenders.append(f"{path.name}: imports {module}")
        for declaration in forbidden_declarations:
            if declaration in text:
                offenders.append(f"{path.name}: {declaration}")
    assert offenders == [], (
        "route memory is P-4's; C-2 binds to a graph it is handed:\n" + "\n".join(offenders)
    )


# --------------------------------------------------------------------------
# 13. The real stream — offline, from C-1's published frames.
# --------------------------------------------------------------------------


def test_the_fixture_is_the_real_c1_stream() -> None:
    payload = json.loads(FIXTURE.read_text())
    assert payload["source_summary_sha256"] == (
        "1dff417b790f1dbd7b47d09deb74b0f52d9a0211e4e38760676d31bff57a6db9"
    )
    assert len(payload["frames"]) == 16
    assert sum(len(f["detections"]) for f in payload["frames"]) == 40


def test_a_map_builds_from_the_real_stream_and_finds_one_lamppost() -> None:
    m = fresh_map()
    for frame in real_frames():
        m.note_frame(frame.queries)
        m.note_pose(frame.robot_x, frame.robot_y)
        for observation in observations_from_frame(
            frame, visit_id="replay", provenance=PROV
        ):
            m.observe(observation)

    labels = [e.label for e in m.entries()]
    assert "lamppost" in labels
    # The stream asked about persons too, and no person is a place.
    assert "person" not in labels
    lamp = max(
        (e for e in m.entries() if e.label == "lamppost"),
        key=lambda e: e.evidence_frames,
    )
    assert lamp.evidence_frames >= 5
    assert lamp.hygiene_note == NOTE_RELIEF_UNVERIFIED
    assert lamp.provenance.detector_name == "owlv2-b16-int8"


def test_the_real_stream_is_stale_and_the_map_says_so() -> None:
    from parcel_robot.online_map.ingest import map_freshness_report

    frames = real_frames()
    report = map_freshness_report(frames)
    assert report["frames"] == 16
    assert report["expired_at_publish"] == 16
    assert report["expired_fraction"] == pytest.approx(1.0)


def test_require_fresh_yields_nothing_on_this_stream() -> None:
    """The strict reading, available and correct for authority — and wrong for
    a map, which is why it is not the default."""

    frames = real_frames()
    total = sum(
        len(observations_from_frame(f, visit_id="v", provenance=PROV,
                                    require_fresh=True))
        for f in frames
    )
    assert total == 0
