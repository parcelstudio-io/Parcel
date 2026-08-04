from __future__ import annotations

import json
import re
import threading
import time
import urllib.request

import pytest

from parcel_robot import web_panel
from parcel_robot.web_panel import VIEWER_UI_PATH, RuntimeHTTPServer

REQUIRED_GEOM_KEYS = {"name", "class", "type", "pos", "zrot_rad", "size", "rgba", "dynamic"}
ALLOWED_GEOM_TYPES = {"plane", "sphere", "capsule", "cylinder", "box"}
MIN_STATIC_GEOMS = 30


class FakeRuntime:
    def snapshot(self):
        return {"status": "test"}

    def latency_snapshot(self):
        return {"aggregate": {}, "turns": []}


@pytest.fixture
def panel_server():
    runtime = FakeRuntime()
    server = RuntimeHTTPServer(("127.0.0.1", 0), runtime)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1.0)


def _get(url: str):
    return urllib.request.urlopen(url, timeout=30)


def test_viewer_route_serves_the_canvas_page(panel_server):
    base = f"http://127.0.0.1:{panel_server.server_address[1]}"
    with _get(f"{base}/viewer") as response:
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("text/html")
        page = response.read().decode()
    assert '<canvas id="cityCanvas"' in page
    assert "Parcel City Viewer" in page
    assert "/api/scene" in page
    assert "/api/state" in page
    # The alias path serves the identical document.
    with _get(f"{base}/viewer.html") as response:
        assert response.read().decode() == page


def test_viewer_page_is_fully_self_contained():
    page = VIEWER_UI_PATH.read_text(encoding="utf-8")
    assert not re.search(r"https?://", page), "viewer.html must not reference external hosts"
    assert not re.search(r"<(script|link|img|iframe)[^>]+(src|href)=", page)
    assert "<style>" in page and "<script>" in page


def test_api_scene_returns_wellformed_static_geometry(panel_server):
    base = f"http://127.0.0.1:{panel_server.server_address[1]}"
    with _get(f"{base}/api/scene") as response:
        assert response.status == 200
        payload = json.load(response)

    assert set(payload) == {"scene", "geom_count", "geoms", "extent", "semantics"}
    geoms = payload["geoms"]
    assert payload["geom_count"] == len(geoms)
    static_geoms = [geom for geom in geoms if not geom["dynamic"]]
    assert len(static_geoms) >= MIN_STATIC_GEOMS

    for geom in geoms:
        assert set(geom) == REQUIRED_GEOM_KEYS
        assert isinstance(geom["name"], str)
        assert geom["type"] in ALLOWED_GEOM_TYPES
        assert len(geom["pos"]) == 3
        assert len(geom["size"]) == 3
        assert len(geom["rgba"]) == 4
        assert all(isinstance(value, (int, float)) for value in geom["pos"])
        assert all(isinstance(value, (int, float)) for value in geom["size"])
        assert all(0.0 <= value <= 1.0 for value in geom["rgba"])
        assert isinstance(geom["zrot_rad"], (int, float))
        assert isinstance(geom["dynamic"], bool)

    classes = {geom["class"] for geom in static_geoms}
    assert {"building", "sidewalk", "road", "crosswalk"} <= classes
    # Robot geoms (the free-jointed tree) must never leak into the payload.
    assert all(not geom["name"].startswith(("FL_", "FR_", "RL_", "RR_")) for geom in geoms)

    extent = payload["extent"]
    assert set(extent) == {"xmin", "xmax", "ymin", "ymax"}
    assert extent["xmin"] < extent["xmax"]
    assert extent["ymin"] < extent["ymax"]

    semantics = payload["semantics"]
    assert set(semantics) == {"regions", "objects"}
    assert isinstance(semantics["regions"], list)
    assert isinstance(semantics["objects"], list)


def test_scene_geometry_is_cached_and_stable(panel_server):
    base = f"http://127.0.0.1:{panel_server.server_address[1]}"
    with _get(f"{base}/api/scene") as response:
        first = json.load(response)
    started = time.perf_counter()
    with _get(f"{base}/api/scene") as response:
        second = json.load(response)
    assert time.perf_counter() - started < 1.0, "cached scene responses must be fast"
    assert first == second
    # The module-level cache hands back the identical object per scene path.
    assert web_panel.scene_geometry() is web_panel.scene_geometry()


def test_semantic_geom_class_prefix_mapping():
    assert web_panel.semantic_geom_class("bldg_3") == "building"
    assert web_panel.semantic_geom_class("tree_top_1") == "tree_canopy"
    assert web_panel.semantic_geom_class("tree_1") == "tree"
    assert web_panel.semantic_geom_class("xw2") == "crosswalk"
    assert web_panel.semantic_geom_class("sidewalk_south") == "sidewalk"
    assert web_panel.semantic_geom_class("obstacle_bollard") == "obstacle"
    assert web_panel.semantic_geom_class("pedestrian_4_head") == "pedestrian"
    assert web_panel.semantic_geom_class("mystery_geom") == "misc"
