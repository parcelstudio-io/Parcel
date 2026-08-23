"""Card P1-B — the map learns from pixels.

Five properties, each one a defect this card closed:

1. **Embeddings + their space reach the map.** The ingress publishes crop
   embeddings with a declared space; the map's seam types them; an embedding
   with no space is refused at the seam, not three layers down.
2. **Depth reaches the planarity gate.** Detections carry a bounded depth grid,
   so ``relief_m`` is a measurement instead of ``relief_unverified``. MOVE-1's
   three patrol runs are the prior: 100 % ``relief_unverified``, all three.
3. **AU-C2-1 — the source crop survives persistence.** ``MapEntry.as_dict``
   omitted the thumbnail and ``from_mapping`` could not restore it, so the
   store dropped every crop in silence. Round-tripped here.
4. **The query batch is bounded and loud.** Refutation D-R2: the P0-D union
   could exceed the 16-phrase frame limit, after which every poll raised inside
   ``poll_once`` and the camera went silently blind.
5. **One store, one world.** Entries carry a typed ``EvidenceOrigin`` and a
   store mixing PHYSICAL with SIMULATION is refused at load.

Plus refutation D-R1: ``pinned_queries`` is set at the attach site, so the
operator's configured batch is pinned INSIDE the ingress rather than surviving
only because one caller happened to re-supply it by hand.

Offline-first. Nothing here starts a simulator, opens a socket, or touches the
owner's store; the dev-scene run that produced the card's measured rows lives in
``scrum/20260822/task_7/`` and is not re-run by the suite.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.camera_channel.ingress import (
    MAX_DEPTH_PATCH_EDGE,
    MAX_EMBEDDING_DIM,
    MAX_QUERY_PHRASES,
    MAX_THUMBNAIL_BYTES,
    SAFETY_LEASE_QUERY,
    CameraDetectionFrame,
    CameraDetectionRecord,
    CameraIngress,
    _decimated_depth_patch,
    _encode_thumbnail,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.online_map import (
    MAP_SCHEMA,
    MIGRATABLE_SCHEMAS,
    EmbeddingStamp,
    MapEntry,
    MapRefused,
    MapStoreRefused,
    OnlineMapStore,
    OnlineSemanticMap,
    WriterProvenance,
    embedding_stamp_from_record,
    normalize_origin,
    observation_from_record,
    observations_from_frame,
    origins_conflict,
)
from parcel_robot.online_map import entries as entries_module

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# fixtures — a frame the ingress could really have published
# --------------------------------------------------------------------------


def _provenance(origin: str = "simulation", scene: str = "city_block") -> WriterProvenance:
    return WriterProvenance(
        session_id="p1b-test",
        seat="runtime_camera",
        detector_name="owlv2-b16-fp16",
        scene_id=scene,
        origin=origin,
    )


def _vector(dim: int = 768, seed: float = 0.1) -> tuple[float, ...]:
    return tuple(seed + i * 1e-4 for i in range(dim))


def _depth_patch(rows: int = 12, cols: int = 12, spread: float = 0.4) -> tuple[tuple[float, ...], ...]:
    """A patch with a real front-to-back spread: a solid object, not a poster."""

    return tuple(
        tuple(2.0 + spread * (r / max(1, rows - 1)) for _ in range(cols))
        for r in range(rows)
    )


def _flat_patch(rows: int = 12, cols: int = 12) -> tuple[tuple[float, ...], ...]:
    """Every sample at one depth: a printed poster, a decal, a painted door."""

    return tuple(tuple(2.0 for _ in range(cols)) for _ in range(rows))


def _record(
    *,
    label: str = "lamppost",
    embedded: bool = True,
    thumbnail: bytes | None = b"\x89PNG-thumb",
    patch: Any = None,
    world_x: float = 3.0,
) -> CameraDetectionRecord:
    return CameraDetectionRecord(
        label=label,
        score=0.71,
        # 80 x 360 px at 3.3 m and fx=fy=644 -> 0.41 m x 1.84 m, inside the
        # lamppost size prior (w 0.04-1.2, h 1.5-9.0). The hygiene gate is
        # C-2's and this card does not move it, so the fixture has to be a
        # plausible lamppost rather than the gate being loosened for a test.
        box=(100.0, 40.0, 180.0, 400.0),
        world_x=world_x,
        world_y=1.5,
        world_z=1.1,
        range_m=3.4,
        bearing_rad=0.2,
        depth_m=3.3,
        sigma_range_m=0.02,
        inlier_pixels=4200,
        embedding=_vector() if embedded else None,
        embedding_model_id="siglip2-base-patch16-224" if embedded else "",
        embedding_revision="vision_model_fp16.onnx" if embedded else "",
        embedding_preprocessing="resize224-rescale-meanstd" if embedded else "",
        thumbnail=thumbnail,
        depth_patch=_depth_patch() if patch is None else patch,
    )


def _frame(
    records: tuple[CameraDetectionRecord, ...] | None = None,
    *,
    origin: str = "simulation",
    queries: tuple[str, ...] = ("person", "lamppost"),
) -> CameraDetectionFrame:
    rows = (_record(),) if records is None else records
    return CameraDetectionFrame(
        frame_id="cam-1-99",
        sequence=1,
        source_timestamp_ns=99,
        capture_started_monotonic_ns=1_000,
        capture_completed_monotonic_ns=2_000,
        published_monotonic_ns=3_000,
        published_wall_s=1_700_000_000.5,
        detection_ttl_ns=300_000_000,
        width_px=640,
        height_px=480,
        robot_x=1.0,
        robot_y=2.0,
        robot_yaw_rad=0.1,
        queries=queries,
        detections=rows,
        raw_detections=len(rows),
        localized_detections=len(rows),
        rejected_detections=0,
        truncated_detections=0,
        render_ms=4.0,
        detect_ms=98.0,
        total_ms=104.0,
        detector_name="owlv2-b16-fp16",
        provider_profile="cuda_fp16",
        active_providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
        origin=origin,
        embedded_detections=sum(1 for r in rows if r.embedded),
        relief_measured_detections=sum(1 for r in rows if r.depth_patch is not None),
    )


class _StubDetector:
    name = "stub"

    def detect(self, *args: Any, **kwargs: Any) -> list[Any]:  # pragma: no cover
        del args, kwargs
        return []


# ==========================================================================
# 1. embeddings + their space reach the map
# ==========================================================================


def test_a_detection_carries_a_real_embedding_and_its_space() -> None:
    record = _record()
    assert record.embedded is True
    assert len(record.embedding or ()) == 768

    stamp = embedding_stamp_from_record(record)
    assert isinstance(stamp, EmbeddingStamp)
    assert stamp.dim == 768
    assert "siglip2" in stamp.model_id
    # The revision is the ARTIFACT, so an fp16 run and an int8 run are two
    # spaces and the map declines to compare across them.
    assert stamp.revision == "vision_model_fp16.onnx"


def test_the_map_entry_ends_up_in_the_siglip_space_not_the_label_hash() -> None:
    """SEED-RED before this card: no ``embed_fn`` at the attach site, so every
    entry carried ``label_embedding`` — an 8-dim hash of the WORD."""

    m = OnlineSemanticMap(provenance=_provenance())
    frame = _frame()
    m.note_frame(queries=frame.queries)
    for observation in observations_from_frame(
        frame, visit_id="v1", provenance=m.provenance
    ):
        m.observe(observation)

    entry = m.entries()[0]
    assert entry.embedding_stamp is not None
    assert entry.embedding_stamp.dim == 768
    assert entry.embedding is not None and len(entry.embedding) == 768
    assert m.stats()["entries_embedded"] == 1


def test_an_embedding_with_no_space_is_refused_at_the_seam() -> None:
    """REVISION 2. A vector in an unknown space is not comparable to anything.

    Refused twice, on purpose: the RECORD refuses to be built, and the seam
    refuses a duck-typed record that got past that (a fixture, a stub, a future
    producer). One of those two is the message whose producer can be fixed.
    """

    with pytest.raises(ValueError, match="unknown space"):
        _record(embedded=True).__class__(
            label="lamppost",
            score=0.5,
            box=(0.0, 0.0, 10.0, 10.0),
            world_x=1.0,
            world_y=1.0,
            world_z=1.0,
            range_m=1.0,
            bearing_rad=0.0,
            depth_m=1.0,
            sigma_range_m=0.01,
            inlier_pixels=10,
            embedding=_vector(8),
        )

    class _Unstamped:
        label = "lamppost"
        score = 0.5
        box = (0.0, 0.0, 10.0, 10.0)
        world_x = world_y = world_z = 1.0
        range_m = 1.0
        bearing_rad = 0.0
        depth_m = 1.0
        inlier_pixels = 10
        embedding = _vector(8)
        embedding_model_id = ""

    with pytest.raises(ValueError, match="embedding with no embedding space"):
        observation_from_record(
            _Unstamped(), frame=_frame(), visit_id="v", provenance=_provenance()
        )


def test_declaring_a_space_without_an_encoder_is_refused() -> None:
    with pytest.raises(ValueError, match="no embed_fn"):
        CameraIngress(
            backend=object(),
            detector=_StubDetector(),
            embedding_model_id="siglip2",
        )


def test_an_encoder_without_a_declared_space_is_refused() -> None:
    with pytest.raises(ValueError, match="no\\s+embedding_model_id"):
        CameraIngress(
            backend=object(),
            detector=_StubDetector(),
            embed_fn=lambda crop: (0.1, 0.2),
        )


def test_the_two_ends_of_the_seam_agree_about_their_bounds() -> None:
    """A ceiling the producer and the store disagree about is a store that
    refuses what the stream is entitled to produce."""

    assert MAX_THUMBNAIL_BYTES == entries_module.MAX_THUMBNAIL_BYTES
    assert MAX_EMBEDDING_DIM == entries_module.MAX_EMBEDDING_DIM


# ==========================================================================
# 2. depth reaches the planarity gate
# ==========================================================================


def test_an_entry_reports_measured_relief_instead_of_relief_unverified() -> None:
    """SEED-RED before this card: MOVE-1's three patrol runs, 100 % of entries
    ``relief_unverified`` — not "flat", but "nobody ever looked"."""

    m = OnlineSemanticMap(provenance=_provenance())
    frame = _frame()
    m.note_frame(queries=frame.queries)
    for observation in observations_from_frame(
        frame, visit_id="v1", provenance=m.provenance
    ):
        assert observation.relief_m is not None
        assert observation.relief_samples >= 8
        m.observe(observation)

    entry = m.entries()[0]
    assert entry.relief_m is not None
    assert entry.hygiene_note != "relief_unverified"
    assert m.stats()["entries_relief_measured"] == 1


def test_a_flat_patch_still_measures_and_the_gate_can_see_it() -> None:
    """A poster of a door measures ~0 relief. The point of the gate is that
    "measured 0.0" and "never measured" stop looking the same."""

    record = _record(patch=_flat_patch())
    observation = observation_from_record(
        record, frame=_frame(), visit_id="v", provenance=_provenance()
    )
    assert observation.relief_m == pytest.approx(0.0)
    assert observation.relief_samples >= 8


def test_a_detection_without_depth_is_unknown_never_flat() -> None:
    """``keep_depth_patches: false``, or a box with nothing measurable in it.
    The map must then say ``relief_unverified``, which means "nobody looked" —
    never "flat", which is what a poster looks like."""

    template = _record()
    bare = CameraDetectionRecord(
        label=template.label,
        score=template.score,
        box=template.box,
        world_x=template.world_x,
        world_y=template.world_y,
        world_z=template.world_z,
        range_m=template.range_m,
        bearing_rad=template.bearing_rad,
        depth_m=template.depth_m,
        sigma_range_m=template.sigma_range_m,
        inlier_pixels=template.inlier_pixels,
    )
    assert bare.depth_patch is None
    observation = observation_from_record(
        bare, frame=_frame(), visit_id="v", provenance=_provenance()
    )
    assert observation.relief_m is None
    assert observation.relief_samples == 0

    m = OnlineSemanticMap(provenance=_provenance())
    m.note_frame(queries=("lamppost",))
    m.observe(observation)
    assert m.entries()[0].hygiene_note == "relief_unverified"
    assert m.stats()["entries_relief_measured"] == 0


def test_the_depth_patch_is_bounded_and_declines_to_answer_when_it_cannot() -> None:
    numpy = pytest.importorskip("numpy")
    depth = numpy.full((480, 640), 2.5, dtype=numpy.float64)
    patch = _decimated_depth_patch(
        depth, (0, 0, 640, 480), depth_min_m=0.4, depth_max_m=6.0
    )
    assert patch is not None
    assert len(patch) <= MAX_DEPTH_PATCH_EDGE
    assert all(len(row) <= MAX_DEPTH_PATCH_EDGE for row in patch)

    # A box whose depths are all out of band carries fewer than the map's own
    # minimum sample count; saying nothing beats shipping a patch that cannot
    # answer and having it come back as ``(None, n)``.
    blind = numpy.full((480, 640), 99.0, dtype=numpy.float64)
    assert (
        _decimated_depth_patch(blind, (0, 0, 64, 64), depth_min_m=0.4, depth_max_m=6.0)
        is None
    )
    # A degenerate box is not an error either.
    assert (
        _decimated_depth_patch(depth, (10, 10, 10, 10), depth_min_m=0.4, depth_max_m=6.0)
        is None
    )


# ==========================================================================
# 3. AU-C2-1 — the source crop survives persistence
# ==========================================================================


def test_the_source_crop_survives_a_store_round_trip(tmp_path: Path) -> None:
    """AU-C2-1, the audit's one refutation, closed and pinned.

    ``MapEntry`` held a bounded thumbnail in memory, ``as_dict`` omitted it and
    ``from_mapping`` could not restore it, so ``OnlineMapStore.save`` dropped
    every crop in silence. Lazy re-embedding across a model upgrade then had no
    source evidence after one reload — the exact migration REVISION §6 exists
    to protect.
    """

    path = tmp_path / "dogmap.sqlite3"
    crop = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 3
    store = OnlineMapStore(path)
    m = OnlineSemanticMap(store, provenance=_provenance())
    frame = _frame((_record(thumbnail=crop),))
    m.note_frame(queries=frame.queries)
    for observation in observations_from_frame(
        frame, visit_id="v1", provenance=m.provenance
    ):
        m.observe(observation)
    before = m.entries()[0]
    assert before.thumbnail == crop
    assert m.persist() == 1
    store.close()

    reloaded = OnlineMapStore(path)
    m2 = OnlineSemanticMap(reloaded, provenance=_provenance())
    after = m2.entries()[0]
    assert after.thumbnail == crop, "AU-C2-1: the source crop was dropped on persist"
    # And the WHOLE entry round-trips, not just the crop.
    assert after.as_dict() == before.as_dict()
    assert after.embedding_stamp is not None
    assert after.embedding_stamp.space_key == before.embedding_stamp.space_key
    reloaded.close()


def test_a_persisted_store_is_one_self_contained_file(tmp_path: Path) -> None:
    """Verification correction, 2026-08-22. SEED: no ``close()``.

    The store opens ``journal_mode=WAL``, so ``persist()`` COMMITS rows and
    leaves them in ``<store>-wal`` until something checkpoints. SQLite
    checkpoints when the last connection closes — and the runtime never closed
    one, so the rows sat in a sidecar until interpreter exit. Anything reading
    the store file during or right after a run (an operator, a copy, an
    evidence pack hashing it) saw fewer places than the robot had learned.

    Measured through a SECOND connection, which is what a reader really is: a
    connection that has never seen this WAL. Before the fix it read 0 rows.
    """

    path = tmp_path / "wal.sqlite3"
    store = OnlineMapStore(path)
    m = OnlineSemanticMap(store, provenance=_provenance())
    frame = _frame()
    m.note_frame(queries=frame.queries)
    for observation in observations_from_frame(
        frame, visit_id="v", provenance=m.provenance
    ):
        m.observe(observation)
    assert m.persist() == 1
    m.close()

    assert not path.with_name(path.name + "-wal").exists(), (
        "the WAL survived close(): the store file is not self-contained"
    )
    # A reader that only ever sees the .sqlite3 finds every row.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM map_entries").fetchone()
    finally:
        conn.close()
    assert count == 1


def test_closing_the_map_releases_the_store_but_keeps_the_entries(tmp_path: Path) -> None:
    """Closing is releasing the FILE, not forgetting the places.

    Teardown still reads ``entries()`` for the snapshot after the persist, and
    persisting a map whose store is gone is a refusal rather than a silent
    no-op that would look exactly like a successful write.
    """

    path = tmp_path / "closed.sqlite3"
    m = OnlineSemanticMap(OnlineMapStore(path), provenance=_provenance())
    frame = _frame()
    m.note_frame(queries=frame.queries)
    for observation in observations_from_frame(
        frame, visit_id="v", provenance=m.provenance
    ):
        m.observe(observation)
    m.persist()
    m.close()
    m.close()  # idempotent

    assert m.store is None
    assert len(m.entries()) == 1
    with pytest.raises(MapRefused, match="no store"):
        m.persist()


def test_the_runtime_closes_the_store_after_persisting() -> None:
    """The seam, by name: a persist that leaves the connection open is the
    defect above, and a failed persist must still release the file."""

    runtime_src = (REPO / "src" / "parcel_robot" / "runtime.py").read_text(
        encoding="utf-8"
    )
    # The close must be on the SUCCESS path, inside the lock, immediately after
    # the write — not merely somewhere in the neighbourhood. Checked as that
    # exact adjacency so the seed (`learned.close()` -> `pass`) cannot be
    # satisfied by the separate `_p1b_close_learned_map` helper below it.
    assert (
        "                learned.close()\n            self._p1b_persisted = written"
        in runtime_src
    ), "the store is not closed inside the lock right after persisting"

    marker = "def _p1b_persist_learned_map"
    body = runtime_src[runtime_src.index(marker) :]
    body = body[: body.index("\n    def learned_map_snapshot")]
    # ...and the failure/no-persist paths must still release the file.
    assert body.count("_p1b_close_learned_map") >= 3


def test_the_map_is_stamped_with_the_scene_not_the_config_filename() -> None:
    """Verification correction, 2026-08-22. SEED: the old derivation.

    ``scene_id`` read ``Path(self._camera_scene_path or self.store.path).stem``,
    and ``_camera_scene_path`` is set by the camera attach, which runs AFTER
    this card's install. So the fallback always won and every entry in every
    run was stamped with the stem of the ROBOT CONFIG file — the dev-scene
    packs said ``p1b``, a throwaway YAML, where they meant ``city_block``.
    """

    from parcel_robot.runtime import RobotRuntime

    runtime = object.__new__(RobotRuntime)
    runtime._camera_scene_path = None
    runtime.store = type(
        "_Store",
        (),
        {"path": str(REPO / "configs" / "robot.yaml")},
    )()
    scene_id = RobotRuntime._p1b_scene_id(runtime)
    assert scene_id != "robot", (
        "scene_id fell back to the robot-config filename again"
    )
    # It resolves through the same function the camera attach uses.
    from parcel_robot.sim import resolve_scene

    assert scene_id == resolve_scene(REPO / "configs" / "robot.yaml", None).stem

    # An explicit scene path still wins, and an unresolvable one says so.
    # A NEUTRAL invented filename on purpose. This line used to name the
    # held-out scene, which put that name in a file the E-2 isolation scan
    # reads — a gratuitous reference, since the assertion only needs "an
    # explicit path wins and keeps its stem".
    runtime._camera_scene_path = "/tmp/somewhere/desk_room.xml"
    assert RobotRuntime._p1b_scene_id(runtime) == "desk_room"
    runtime._camera_scene_path = None
    runtime.store = type("_Store", (), {"path": "/nonexistent/nope.yaml"})()
    assert RobotRuntime._p1b_scene_id(runtime) in {"nope", "unknown", "city_block"}


def test_a_corrupt_thumbnail_is_a_refusal_not_a_shrug() -> None:
    """A crop that silently decoded to garbage would re-embed to a vector
    describing nothing while looking exactly like success."""

    entry = MapEntry(
        entry_id="e1",
        label="tree",
        surface_x=1.0,
        surface_y=1.0,
        surface_z=1.0,
        provenance=_provenance(),
        first_seen_wall_s=1.0,
        last_seen_wall_s=2.0,
    )
    payload = entry.as_dict()
    assert payload["thumbnail"] is None

    payload["thumbnail"] = "not base64!!"
    with pytest.raises(ValueError, match="not valid base64"):
        MapEntry.from_mapping(payload)

    payload["thumbnail"] = 17
    with pytest.raises(TypeError, match="base64 string or null"):
        MapEntry.from_mapping(payload)


def test_a_v1_store_migrates_forward_instead_of_being_refused(tmp_path: Path) -> None:
    """The schema bump is additive, so a v1 store is MIGRATED, not thrown away.

    A v1 row genuinely had no thumbnail and no origin, and ``None``/``unknown``
    is exactly what it meant. The migration re-reads every row through
    ``from_mapping`` before relabelling, so a row this build cannot parse leaves
    the store on v1 rather than being silently relabelled and failing later.
    """

    path = tmp_path / "v1.sqlite3"
    store = OnlineMapStore(path)
    store.save(
        MapEntry(
            entry_id="e0",
            label="tree",
            surface_x=1.0,
            surface_y=2.0,
            surface_z=0.5,
            provenance=_provenance(),
            first_seen_wall_s=1.0,
            last_seen_wall_s=2.0,
            thumbnail=b"xyz",
        )
    )
    store.close()

    # Rewrite it as a genuine v1 store: v1 schema string, v1 row shape.
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "UPDATE map_meta SET value = ? WHERE key = 'schema'",
            (MIGRATABLE_SCHEMAS[0],),
        )
        (payload,) = conn.execute("SELECT payload FROM map_entries").fetchone()
        data = json.loads(payload)
        data.pop("thumbnail")
        data["provenance"].pop("origin")
        conn.execute(
            "UPDATE map_entries SET payload = ?",
            (json.dumps(data, sort_keys=True, separators=(",", ":")),),
        )
    conn.close()

    migrated = OnlineMapStore(path)
    assert migrated.get_meta("schema") == MAP_SCHEMA
    assert migrated.get_meta("migrated_from") == MIGRATABLE_SCHEMAS[0]
    assert migrated.get_meta("migrated_rows") == "1"
    entry = migrated.load_all()[0]
    assert entry.thumbnail is None
    assert entry.provenance.origin == EvidenceOrigin.UNKNOWN.value
    migrated.close()


def test_an_unknown_schema_is_still_refused(tmp_path: Path) -> None:
    path = tmp_path / "v0.sqlite3"
    OnlineMapStore(path).close()
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("UPDATE map_meta SET value = 'parcel.online_map.v0' WHERE key = 'schema'")
    conn.close()
    with pytest.raises(MapStoreRefused, match="Refusing to reinterpret"):
        OnlineMapStore(path)


# ==========================================================================
# 4. the query batch is bounded and LOUD  (refutation D-R2)
# ==========================================================================


def test_the_query_union_is_capped_and_the_drop_is_counted() -> None:
    """SEED-RED (P0-D's union, uncapped): a 20-phrase batch made EVERY frame
    fail construction inside ``poll_once``, which swallowed the exception —
    silent blindness, with only ``stats.errors`` moving."""

    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    ingress.pinned_queries = ("person", "lamppost", "tree")
    ingress.set_query(tuple(f"thing-{i}" for i in range(20)))

    batch = ingress.stats.last_query
    assert len(batch) == MAX_QUERY_PHRASES
    assert SAFETY_LEASE_QUERY in batch
    assert ingress.stats.queries_dropped == (3 + 20) - MAX_QUERY_PHRASES
    assert ingress.stats.last_dropped_queries
    # The capped batch is a batch a frame will actually accept, which is the
    # whole point: construct one and it does not raise.
    _frame(queries=batch)


def test_the_safety_lease_is_never_the_phrase_that_falls_off_the_end() -> None:
    """``person`` may arrive anywhere in the batch. It may not be truncated."""

    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    ingress.pinned_queries = tuple(f"pinned-{i}" for i in range(20)) + ("a person",)
    ingress.set_query(("bench",))
    batch = ingress.stats.last_query
    assert len(batch) == MAX_QUERY_PHRASES
    assert any(SAFETY_LEASE_QUERY in phrase.lower().split() for phrase in batch)


def test_a_batch_under_the_cap_is_untouched_and_counts_nothing() -> None:
    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    ingress.pinned_queries = ("person", "lamppost")
    ingress.set_query(("bench",))
    assert ingress.stats.last_query == ("person", "lamppost", "bench")
    assert ingress.stats.queries_dropped == 0
    assert ingress.stats.last_dropped_queries == ()


def test_clear_query_still_turns_the_eye_off(tmp_path: Path) -> None:
    """The cap is not an excuse to change what ``clear_query`` means."""

    del tmp_path
    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    ingress.pinned_queries = ("person", "lamppost")
    ingress.set_query(("bench",))
    ingress.clear_query()
    assert ingress.stats.last_query == ()
    assert ingress.has_query is False


def test_a_frame_over_the_cap_is_still_a_hard_refusal() -> None:
    """The cap is a producer-side guard; the schema's own ceiling stays."""

    with pytest.raises(ValueError, match="exceeds 16 phrases"):
        _frame(queries=tuple(f"q{i}" for i in range(17)))


# ==========================================================================
# 5. one store, one world  (EvidenceOrigin)
# ==========================================================================


def test_every_entry_is_stamped_with_the_origin_of_its_frames() -> None:
    m = OnlineSemanticMap(provenance=_provenance(origin="simulation"))
    frame = _frame(origin="simulation")
    m.note_frame(queries=frame.queries)
    for observation in observations_from_frame(
        frame, visit_id="v", provenance=m.provenance
    ):
        m.observe(observation)
    entry = m.entries()[0]
    assert entry.provenance.evidence_origin is EvidenceOrigin.SIMULATION
    assert entry.provenance.is_physical is False
    assert m.stats()["origin"] == "simulation"


def test_a_store_mixing_physical_and_simulated_entries_is_refused(tmp_path: Path) -> None:
    """SEED-RED without the check: the two rows are identical apart from one
    field nobody reads, so the renderer's places quietly borrow the camera's
    credibility and every aggregate over the store blends two worlds."""

    path = tmp_path / "mixed.sqlite3"
    store = OnlineMapStore(path)
    for index, origin in enumerate(("simulation", "physical")):
        store.save(
            MapEntry(
                entry_id=f"e{index}",
                label="chair",
                surface_x=float(index),
                surface_y=1.0,
                surface_z=0.5,
                provenance=_provenance(origin=origin, scene=f"scene-{index}"),
                first_seen_wall_s=1.0,
                last_seen_wall_s=2.0,
            )
        )
    store.close()

    reopened = OnlineMapStore(path)
    with pytest.raises(MapStoreRefused, match="mixes evidence origins"):
        reopened.load_all()
    reopened.close()


def test_unknown_is_silent_not_synthetic(tmp_path: Path) -> None:
    """Refusing every pre-P1-B store would make this guard the first thing a
    future executor deletes. ``unknown`` has not claimed anything."""

    assert origins_conflict({"physical", "unknown"}) is False
    assert origins_conflict({"simulation", "unknown"}) is False
    assert origins_conflict({"physical", "simulation"}) is True
    assert origins_conflict({"physical", "replay"}) is True

    path = tmp_path / "mixed_unknown.sqlite3"
    store = OnlineMapStore(path)
    for index, origin in enumerate(("unknown", "physical")):
        store.save(
            MapEntry(
                entry_id=f"e{index}",
                label="chair",
                surface_x=float(index),
                surface_y=1.0,
                surface_z=0.5,
                provenance=_provenance(origin=origin),
                first_seen_wall_s=1.0,
                last_seen_wall_s=2.0,
            )
        )
    store.close()
    reopened = OnlineMapStore(path)
    assert len(reopened.load_all()) == 2
    reopened.close()


def test_the_map_refuses_the_frame_that_would_make_the_store_mixed() -> None:
    """The other end of the same invariant, and the useful one: it fires in the
    process that fed the foreign frame, not on whoever reloads tomorrow."""

    m = OnlineSemanticMap(provenance=_provenance(origin="simulation"))
    physical = observation_from_record(
        _record(), frame=_frame(), visit_id="v", provenance=_provenance(origin="physical")
    )
    with pytest.raises(MapRefused, match="two different worlds"):
        m.observe(physical)


def test_an_origin_is_declared_never_spelled() -> None:
    """Card W0-A's lesson: a free-form origin string is an origin a producer can
    claim by spelling."""

    assert normalize_origin(EvidenceOrigin.PHYSICAL) == "physical"
    assert normalize_origin(" Simulation ") == "simulation"
    with pytest.raises(ValueError, match="unknown evidence origin"):
        normalize_origin("definitely_real")
    with pytest.raises(TypeError):
        normalize_origin(1)
    with pytest.raises(ValueError, match="unknown frame origin"):
        _frame(origin="definitely_real")


# ==========================================================================
# the JSONL row stays payload-free, deliberately and provably
# ==========================================================================


def test_the_evidence_row_carries_the_counters_and_not_the_payload() -> None:
    """``_offer_camera_frame_evidence``'s own contract is that raw arrays and
    embeddings never reach JSONL. This card kept that and made the omission a
    stated design choice with a test, rather than the silent drop AU-C2-1 was."""

    frame = _frame()
    row = frame.as_dict()
    text = json.dumps(row)
    assert "embedding" not in text
    assert "thumbnail" not in text
    assert "depth_patch" not in text
    # ...but an auditor can still tell the payload existed, and which world.
    assert row["embedded_detections"] == 1
    assert row["relief_measured_detections"] == 1
    assert row["origin"] == "simulation"
    # And the row still round-trips exactly.
    again = CameraDetectionFrame.from_mapping(row).as_dict()
    assert json.dumps(again, sort_keys=True) == json.dumps(row, sort_keys=True)


def test_a_pre_p1b_frame_row_still_decodes() -> None:
    """C-1 archived 16 real frames before this card existed. Those rows did not
    know their origin, and ``unknown`` plus two zeroes is what they meant."""

    row = _frame().as_dict()
    for key in ("origin", "embedded_detections", "relief_measured_detections"):
        row.pop(key)
    decoded = CameraDetectionFrame.from_mapping(row)
    assert decoded.origin == "unknown"
    assert decoded.embedded_detections == 0
    assert decoded.relief_measured_detections == 0


def test_the_archived_c1_stream_still_loads_and_maps() -> None:
    """The real 16-frame C-1 fixture is the migration's actual subject."""

    fixture = REPO / "tests" / "data" / "c2_online_map_frames.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    frames = [CameraDetectionFrame.from_mapping(row) for row in payload["frames"]]
    assert len(frames) == 16
    assert all(f.origin == "unknown" for f in frames)

    m = OnlineSemanticMap(provenance=_provenance(origin="unknown"))
    for frame in frames:
        m.note_frame(queries=frame.queries)
        m.note_pose(frame.robot_x, frame.robot_y)
        for observation in observations_from_frame(
            frame, visit_id="replay", provenance=m.provenance
        ):
            m.observe(observation)
    # Unchanged from C-2's own result: the archived rows carry no payload, so
    # the map they build is the same map it always was.
    assert len(m) > 0
    assert m.stats()["entries_embedded"] == 0
    assert m.stats()["entries_relief_measured"] == 0


# ==========================================================================
# the thumbnail encoder
# ==========================================================================


def test_the_thumbnail_is_a_real_bounded_png() -> None:
    numpy = pytest.importorskip("numpy")
    crop = numpy.random.default_rng(7).integers(
        0, 255, size=(320, 240, 3), dtype=numpy.uint8
    )
    png = _encode_thumbnail(crop)
    assert png is not None
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) <= MAX_THUMBNAIL_BYTES
    # IHDR carries the decimated size, and the longest edge respects the bound.
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert max(width, height) <= 64
    assert width > 0 and height > 0


def test_the_thumbnail_encoder_never_raises_on_junk() -> None:
    """A thumbnail is a nice-to-have; the camera worker is not."""

    assert _encode_thumbnail(None) is None
    assert _encode_thumbnail("not an image") is None
    assert _encode_thumbnail(object()) is None


# ==========================================================================
# refutation D-R1 — the configured batch is pinned INSIDE the ingress
# ==========================================================================


def test_the_attach_site_pins_the_configured_batch() -> None:
    """SEED-RED (P0-D as shipped): ``pinned_queries`` was never assigned by any
    product code, so the operator's batch survived a directive only because
    ``_set_camera_query_from_directive`` re-supplied it by hand. Any OTHER
    caller of ``set_query`` — the patrol driver, a curiosity refresh — silently
    narrowed the batch to its own phrase plus ``person``.

    Read from the source rather than by booting a MuJoCo runtime: the attach
    site needs EGL, a scene compile and an ONNX session, none of which belong
    in a unit suite. The line is one line and its absence is the defect.
    """

    runtime_src = (REPO / "src" / "parcel_robot" / "runtime.py").read_text(
        encoding="utf-8"
    )
    marker = "def _attach_configured_camera_ingress"
    body = runtime_src[runtime_src.index(marker) :]
    body = body[: body.index("\n    def ", 10)]
    assert "ingress.pinned_queries = tuple(config.queries)" in body, (
        "D-R1: the configured batch is not pinned inside the ingress"
    )
    assert "load_siglip2_embed_fn()" in body, (
        "the SigLIP-2 encoder is not armed at the attach site"
    )
    assert "EvidenceOrigin.SIMULATION.value" in body, (
        "the MuJoCo ingress does not declare its venue"
    )


def test_the_map_settings_block_fails_closed_on_a_typo(tmp_path: Path) -> None:
    """A key nothing reads looks exactly like a switch that never flipped.

    Same discipline as the abstention block and ``semantic_source``: unknown
    keys under ``perception.online_map`` are a hard error, and the wrong type
    is a hard error, so ``persist_on_clos: true`` cannot silently mean "the
    default" for the one setting whose failure loses a run's whole memory.
    """

    from parcel_robot.runtime import RobotRuntime

    runtime = object.__new__(RobotRuntime)

    def _settings(block: dict[str, Any] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"perception": {"semantic_source": "shadow"}}
        if block is not None:
            payload["perception"]["online_map"] = block
        config = tmp_path / f"nav-{abs(hash(json.dumps(payload, sort_keys=True)))}.yaml"
        config.write_text(json.dumps(payload), encoding="utf-8")  # YAML ⊃ JSON
        runtime.store = type(  # minimal duck-typed store
            "_Store",
            (),
            {"section": staticmethod(lambda name: {"config": str(config)})},
        )()
        return RobotRuntime._p1b_map_settings(runtime)

    defaults = _settings(None)
    assert defaults["persist_on_close"] is True
    assert defaults["reload_on_start"] is True
    assert defaults["oracle_query_batch_from_scene"] is False
    assert defaults["curiosity_queries"] == []

    with pytest.raises(ValueError, match="unknown perception.online_map key"):
        _settings({"persist_on_clos": True})
    with pytest.raises(TypeError, match="must be a boolean"):
        _settings({"persist_on_close": "yes"})
    with pytest.raises(TypeError, match="list of strings"):
        _settings({"curiosity_queries": "bench"})

    real = _settings(
        {"curiosity_queries": ["bench", " tree "], "visit_id_prefix": "patrol"}
    )
    assert real["curiosity_queries"] == ["bench", "tree"]
    assert real["visit_id_prefix"] == "patrol"


def test_the_shipped_navigation_default_builds_no_map() -> None:
    """R1 flag-off identity, in the file rather than only in a run.

    ``configs/navigation/default.yaml`` names ``oracle`` and carries no
    ``online_map`` block, so ``reads_learned_map`` is False, the runtime's
    region returns before constructing anything, and the camera batch is
    exactly ``perception.camera_ingress_queries`` — byte-identical to before
    this card. The 25 s oracle run in ``evidence/p1b_flag_off/`` measures the
    same thing end-to-end (``learned_map_snapshot() is None``, no store file
    written even with ``PARCEL_ONLINE_MAP_PATH`` set).
    """

    import yaml

    from parcel_robot.perception_source import SemanticSourcePolicy

    raw = yaml.safe_load(
        (REPO / "configs" / "navigation" / "default.yaml").read_text(encoding="utf-8")
    )
    section = (raw or {}).get("perception") or {}
    assert "online_map" not in section
    policy = SemanticSourcePolicy.from_mapping(section)
    assert policy.is_oracle is True
    assert policy.reads_learned_map is False

    prototype = yaml.safe_load(
        (REPO / "configs" / "navigation" / "prototype.yaml").read_text(encoding="utf-8")
    )
    block = prototype["perception"]["online_map"]
    assert block["persist_on_close"] is True
    assert block["reload_on_start"] is True
    # The oracle-side sidecar batch is measured and OFF; see the block's own
    # comment for the truncation numbers that made it a decision.
    assert block["oracle_query_batch_from_scene"] is False


def test_the_runtime_region_wires_all_three_seams() -> None:
    """The writer is only real if something calls it. Three seams, by name."""

    runtime_src = (REPO / "src" / "parcel_robot" / "runtime.py").read_text(
        encoding="utf-8"
    )
    assert "self._p1b_install_learned_map()" in runtime_src
    assert "self._p1b_feed_learned_map(frame)" in runtime_src
    assert "self._p1b_persist_learned_map()" in runtime_src
    # Install must precede attach, or the first frames land in no map and the
    # query batch cannot be built from what the reloaded map knows.
    #
    # Card XD-1 (scrum/20260822/task_14), carried finding from AUDIT_WAVE2_FABLE:
    # this used to pin the attach with the LITERAL two-line string
    # ``"self._attach_configured_camera_ingress()\n            self._thread"``.
    # That suffix asserts a second, unintended property — that NOTHING may ever
    # sit between the attach and the first thread start — which is not this
    # card's business and is not true of the composition root. It broke on
    # CAP-1's region insertion and forced VENUE-1's remedy into a shape it did
    # not want (see the CAP-1 comment block in ``RobotRuntime.start``). Two
    # index comparisons protect exactly the ordering above and leave the
    # composition root extensible.
    install_at = runtime_src.index("self._p1b_install_learned_map()")
    attach_at = runtime_src.index("self._attach_configured_camera_ingress()")
    assert install_at < attach_at, (
        "the learned map must be installed before the camera ingress attaches: "
        f"install at offset {install_at}, attach at offset {attach_at}"
    )
