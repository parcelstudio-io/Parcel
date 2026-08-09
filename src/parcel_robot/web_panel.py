from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import math
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from parcel_robot.backends import MujocoSocketBackend
from parcel_robot.config import ConfigStore
from parcel_robot.providers import LlamaCppProvider
from parcel_robot.runtime import RobotRuntime
from parcel_robot.sim_ipc import DEFAULT_SOCKET

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "robot.yaml"
FALLBACK_CONFIG = Path(__file__).with_name("config") / "robot.yaml"
UI_PATH = Path(__file__).with_name("ui") / "index.html"
LATENCY_UI_PATH = Path(__file__).with_name("ui") / "latency.html"
VIEWER_UI_PATH = Path(__file__).with_name("ui") / "viewer.html"
EVALS_UI_PATH = Path(__file__).with_name("ui") / "evals.html"
POSE_REVIEW_UI_PATH = Path(__file__).with_name("ui") / "poses.html"
MAX_REQUEST_BYTES = 65_536

#: Ordered (prefix, class) pairs; the first matching prefix wins, so longer
#: prefixes ("tree_top_") must appear before their shorter siblings ("tree_").
SEMANTIC_GEOM_PREFIXES: tuple[tuple[str, str], ...] = (
    ("bldg_", "building"),
    ("window_", "window"),
    ("sidewalk", "sidewalk"),
    ("curb", "curb"),
    ("road", "road"),
    ("asphalt", "road"),
    ("lane_", "lane_marking"),
    ("xw", "crosswalk"),
    ("crosswalk", "crosswalk"),
    ("bench_", "bench"),
    ("tree_top_", "tree_canopy"),
    ("tree_", "tree"),
    ("lamp_head_", "lamp_head"),
    ("lamp_", "lamp"),
    ("planter_", "planter"),
    ("signal_", "signal"),
    ("obstacle_", "obstacle"),
    ("pedestrian_", "pedestrian"),
    ("cyclist_", "cyclist"),
    ("owner", "owner"),
)

_SCENE_CACHE: dict[str, dict[str, Any]] = {}
_SCENE_CACHE_LOCK = threading.Lock()


def semantic_geom_class(name: str) -> str:
    """Map a scene geom name to a coarse semantic class for the viewer."""
    for prefix, label in SEMANTIC_GEOM_PREFIXES:
        if name.startswith(prefix):
            return label
    return "misc"


def resolve_viewer_scene(config_path: Path | None = None) -> Path:
    """Resolve the MuJoCo scene path the same way the simulator does."""
    from parcel_robot.sim import resolve_scene

    if config_path is None:
        config_path = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else FALLBACK_CONFIG
    return resolve_scene(config_path, None)


def scene_geometry(scene_path: Path | None = None) -> dict[str, Any]:
    """Load the static city geometry once and serve a cached JSON-safe dict.

    The MuJoCo model is loaded server-side exactly once per scene path; repeat
    calls return the identical cached object. Robot geoms (the free-jointed
    kinematic tree) are excluded; mocap actor geoms are flagged ``dynamic`` so
    the viewer can style them from live ``/api/state`` tracks instead.
    """
    resolved = (scene_path or resolve_viewer_scene()).expanduser().resolve()
    key = str(resolved)
    with _SCENE_CACHE_LOCK:
        cached = _SCENE_CACHE.get(key)
        if cached is not None:
            return cached
        if not resolved.is_file():
            raise FileNotFoundError(f"MuJoCo scene not found: {resolved}")
        payload = _extract_scene_geometry(resolved)
        _SCENE_CACHE[key] = payload
        return payload


def _extract_scene_geometry(scene_path: Path) -> dict[str, Any]:
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(scene_path))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    type_names = {
        int(mujoco.mjtGeom.mjGEOM_PLANE): "plane",
        int(mujoco.mjtGeom.mjGEOM_SPHERE): "sphere",
        int(mujoco.mjtGeom.mjGEOM_CAPSULE): "capsule",
        int(mujoco.mjtGeom.mjGEOM_CYLINDER): "cylinder",
        int(mujoco.mjtGeom.mjGEOM_BOX): "box",
    }
    default_rgba = (0.5, 0.5, 0.5, 1.0)
    geoms: list[dict[str, Any]] = []
    bounds: list[tuple[float, float]] = []
    for geom_id in range(model.ngeom):
        body_id = int(model.geom_bodyid[geom_id])
        root_id = int(model.body_rootid[body_id])
        is_mocap = int(model.body_mocapid[root_id]) >= 0
        if root_id != 0 and not is_mocap:
            continue  # part of the robot's free-jointed tree
        type_name = type_names.get(int(model.geom_type[geom_id]))
        if type_name is None:
            continue  # meshes / heightfields are not renderable primitives here
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
        rgba = tuple(round(float(value), 4) for value in model.geom_rgba[geom_id])
        material_id = int(model.geom_matid[geom_id])
        if material_id >= 0 and rgba == default_rgba:
            rgba = tuple(round(float(value), 4) for value in model.mat_rgba[material_id])
        matrix = data.geom_xmat[geom_id]
        position = tuple(round(float(value), 4) for value in data.geom_xpos[geom_id])
        size = tuple(round(float(value), 4) for value in model.geom_size[geom_id])
        geoms.append(
            {
                "name": name,
                "class": semantic_geom_class(name),
                "type": type_name,
                "pos": list(position),
                "zrot_rad": round(math.atan2(float(matrix[3]), float(matrix[0])), 4),
                "size": list(size),
                "rgba": list(rgba),
                "dynamic": is_mocap,
            }
        )
        if not is_mocap and type_name != "plane":
            reach = math.hypot(size[0], size[1] if len(size) > 1 else size[0])
            bounds.append((position[0] - reach, position[0] + reach))
            bounds.append((position[1] - reach, position[1] + reach))
    if not geoms:
        raise ValueError(f"scene contains no renderable static geoms: {scene_path}")
    xs = [edge for low, high in bounds[0::2] for edge in (low, high)]
    ys = [edge for low, high in bounds[1::2] for edge in (low, high)]
    extent = {
        "xmin": round(min(xs), 3) if xs else -10.0,
        "xmax": round(max(xs), 3) if xs else 10.0,
        "ymin": round(min(ys), 3) if ys else -10.0,
        "ymax": round(max(ys), 3) if ys else 10.0,
    }
    regions: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []
    try:
        from parcel_robot.city_semantics import extract_city_semantics

        regions, objects = extract_city_semantics(model)
    except (ImportError, AttributeError, KeyError, TypeError, ValueError):
        pass  # semantics are an optional enrichment for the viewer
    return {
        "scene": str(scene_path),
        "geom_count": len(geoms),
        "geoms": geoms,
        "extent": extent,
        "semantics": {"regions": regions, "objects": objects},
    }


class RuntimeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        runtime: RobotRuntime,
        scene_path: Path | None = None,
        *,
        pose_review_enabled: bool = False,
    ):
        self.runtime = runtime
        self.scene_path = scene_path
        self.pose_review_enabled = pose_review_enabled
        self.csrf_token = secrets.token_urlsafe(32)
        super().__init__(address, RuntimeRequestHandler)


class RuntimeRequestHandler(BaseHTTPRequestHandler):
    server: RuntimeHTTPServer

    def do_GET(self) -> None:
        if not self._valid_host():
            self._send_json({"detail": "invalid Host header"}, HTTPStatus.FORBIDDEN)
            return
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            body = UI_PATH.read_text(encoding="utf-8").replace(
                "__PARCEL_CSRF_TOKEN__", self.server.csrf_token
            )
            self._send_bytes(body.encode(), "text/html; charset=utf-8")
            return
        if path in {"/latency", "/latency.html"}:
            self._send_bytes(
                LATENCY_UI_PATH.read_bytes(),
                "text/html; charset=utf-8",
            )
            return
        if path in {"/viewer", "/viewer.html"}:
            self._send_bytes(
                VIEWER_UI_PATH.read_bytes(),
                "text/html; charset=utf-8",
            )
            return
        if path in {"/evals", "/evals.html"}:
            body = EVALS_UI_PATH.read_text(encoding="utf-8").replace(
                "__PARCEL_CSRF_TOKEN__", self.server.csrf_token
            )
            self._send_bytes(body.encode(), "text/html; charset=utf-8")
            return
        if path in {"/poses", "/poses.html"}:
            if not self.server.pose_review_enabled:
                self._send_json({"detail": "pose review is not enabled"}, HTTPStatus.NOT_FOUND)
                return
            body = POSE_REVIEW_UI_PATH.read_text(encoding="utf-8").replace(
                "__PARCEL_CSRF_TOKEN__", self.server.csrf_token
            )
            self._send_bytes(body.encode(), "text/html; charset=utf-8")
            return
        if path == "/api/scene":
            try:
                self._send_json(scene_geometry(self.server.scene_path))
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
                self._send_json({"detail": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if path == "/api/state":
            payload = self.server.runtime.snapshot()
            try:
                from parcel_robot.eval_panel import live_goal_overlay

                overlay = live_goal_overlay()
                if overlay is not None:
                    payload = dict(payload)
                    payload["eval"] = overlay
            except (ImportError, RuntimeError, TypeError, ValueError):
                # Overlay is best-effort; never break /api/state.
                pass
            self._send_json(payload)
            return
        if path == "/api/latency":
            self._send_json(self.server.runtime.latency_snapshot())
            return
        if path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if path == "/api/prompt":
            self._send_json(self.server.runtime.prompt_inspection())
            return
        if path == "/api/pose-review/skills":
            if not self.server.pose_review_enabled:
                self._send_json({"detail": "pose review is not enabled"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(
                {
                    "simulator_only": True,
                    "skills": self.server.runtime.pose_review_skills(),
                }
            )
            return
        if path == "/api/evals/scenarios":
            from parcel_robot.eval_panel import EVAL_PANEL

            EVAL_PANEL.ensure_scenarios()
            self._send_json({"scenarios": EVAL_PANEL.list_scenarios()})
            return
        if path == "/api/evals/status":
            from parcel_robot.eval_panel import EVAL_PANEL

            self._send_json(EVAL_PANEL.snapshot())
            return
        self._send_json({"detail": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            self._authorize_post()
            payload = self._read_json()
            if path == "/api/command":
                turn_id = self.server.runtime.submit_voice_text(
                    self._string(payload, "text"), is_final=True
                )
                self._send_json(
                    {"accepted": True, "turn_id": turn_id},
                    HTTPStatus.ACCEPTED if turn_id is not None else HTTPStatus.OK,
                )
                return
            if path == "/api/voice/text":
                turn_id = self.server.runtime.submit_voice_text(
                    self._string(payload, "text"),
                    is_final=self._boolean(payload, "is_final", True),
                )
                self._send_json(
                    {
                        "accepted": True,
                        "is_final": self._boolean(payload, "is_final", True),
                        "turn_id": turn_id,
                        "state": self.server.runtime.snapshot(),
                    },
                    HTTPStatus.ACCEPTED if turn_id is not None else HTTPStatus.OK,
                )
                return
            if path == "/api/voice/barge-in":
                self._send_json({"message": self.server.runtime.interrupt_voice()})
                return
            if path == "/api/motion":
                message = self.server.runtime.manual_motion(
                    self._number(payload, "vx", 0.0),
                    self._number(payload, "vy", 0.0),
                    self._number(payload, "vyaw", 0.0),
                )
                self._send_json({"message": message})
                return
            if path == "/api/action":
                message = self.server.runtime.action(self._string(payload, "action"))
                self._send_json({"message": message, "state": self.server.runtime.snapshot()})
                return
            if path == "/api/pose-review/run":
                if not self.server.pose_review_enabled:
                    self._send_json(
                        {"detail": "pose review is not enabled"}, HTTPStatus.NOT_FOUND
                    )
                    return
                name = self._string(payload, "name")
                speed = self._optional_normalized_speed(payload, "speed")
                result = self.server.runtime.execute_pose_review(name, speed=speed)
                self._send_json(
                    {
                        "accepted": True,
                        "message": result.message,
                        "name": name,
                        "speed": result.requested_speed,
                        "effective_rate": result.effective_rate,
                        "effective_duration_s": result.effective_duration_s,
                        "state": self.server.runtime.snapshot(),
                    },
                    HTTPStatus.ACCEPTED,
                )
                return
            if path == "/api/owner":
                message = self.server.runtime.move_owner(
                    self._number(payload, "dx", 0.0),
                    self._number(payload, "dy", 0.0),
                )
                self._send_json({"message": message})
                return
            if path == "/api/personality":
                message = self.server.runtime.set_personality(self._string(payload, "personality"))
                self._send_json({"message": message, "state": self.server.runtime.snapshot()})
                return
            if path == "/api/prompt/fact":
                self.server.runtime.set_user_fact(
                    self._string(payload, "key"), self._string(payload, "value")
                )
                self._send_json(self.server.runtime.prompt_inspection())
                return
            if path == "/api/evals/run":
                from parcel_robot.eval_panel import EVAL_PANEL

                episode_id = self._string(payload, "episode_id")
                mode = str(payload.get("mode") or "headless").lower()
                if mode == "voice" or self._boolean(payload, "voice_mode", False):
                    # Product path: the instruction is typed into the live
                    # runtime's handle_text instead of driving the navigator
                    # directly, so admission/routing failures are visible to
                    # the panel. Sequential by construction — start_voice
                    # reuses the existing "already running" guard.
                    selected = EVAL_PANEL.start_voice(episode_id, self.server.runtime)
                    self._send_json({"accepted": True, **selected}, HTTPStatus.ACCEPTED)
                    return
                if mode == "live":
                    selected = EVAL_PANEL.select(episode_id)
                    # Live mode: place start pose is sim-owned; inject instruction.
                    turn_id = self.server.runtime.submit_voice_text(
                        str(selected["instruction"]), is_final=True
                    )
                    self._send_json(
                        {
                            "accepted": True,
                            "mode": "live",
                            "turn_id": turn_id,
                            **selected,
                        },
                        HTTPStatus.ACCEPTED if turn_id is not None else HTTPStatus.OK,
                    )
                    return
                selected = EVAL_PANEL.start_headless(episode_id)
                self._send_json({"accepted": True, "mode": "headless", **selected}, HTTPStatus.ACCEPTED)
                return
            if path == "/api/evals/batch":
                from parcel_robot.eval_panel import EVAL_PANEL

                nav_mode = str(payload.get("nav_mode") or "candidate").lower()
                if nav_mode not in {"baseline", "candidate"}:
                    raise ValueError("nav_mode must be baseline or candidate")
                accepted = EVAL_PANEL.start_batch(mode=nav_mode)
                self._send_json(accepted, HTTPStatus.ACCEPTED)
                return
            if path == "/api/evals/select":
                from parcel_robot.eval_panel import EVAL_PANEL

                selected = EVAL_PANEL.select(self._string(payload, "episode_id"))
                self._send_json(selected)
                return
            self._send_json({"detail": "not found"}, HTTPStatus.NOT_FOUND)
        except PermissionError as error:
            self._send_json({"detail": str(error)}, HTTPStatus.FORBIDDEN)
        except (KeyError, TypeError, ValueError) as error:
            self._send_json({"detail": str(error)}, HTTPStatus.BAD_REQUEST)
        except (ConnectionError, FileNotFoundError, OSError, RuntimeError) as error:
            self._send_json({"detail": str(error)}, HTTPStatus.CONFLICT)

    def do_OPTIONS(self) -> None:
        if not self._valid_host():
            self._send_json({"detail": "invalid Host header"}, HTTPStatus.FORBIDDEN)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        if urlsplit(self.path).path != "/api/state":
            print(f"parcel-panel: {format % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("request body size is invalid")
        raw = self.rfile.read(length)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TypeError("request body must be a JSON object")
        return value

    def _authorize_post(self) -> None:
        if not self._valid_host():
            raise PermissionError("invalid Host header")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise PermissionError("Content-Type must be application/json")
        supplied = self.headers.get("X-Parcel-CSRF", "")
        if not hmac.compare_digest(supplied, self.server.csrf_token):
            raise PermissionError("missing or invalid control token")
        origin = self.headers.get("Origin")
        if origin:
            origin_url = urlsplit(origin)
            host_url = urlsplit(f"http://{self.headers.get('Host', '')}")
            origin_port = origin_url.port or (443 if origin_url.scheme == "https" else 80)
            host_port = host_url.port or 80
            if (
                origin_url.scheme not in {"http", "https"}
                or origin_url.hostname != host_url.hostname
                or origin_port != host_port
            ):
                raise PermissionError("cross-origin control requests are forbidden")

    def _valid_host(self) -> bool:
        host = urlsplit(f"http://{self.headers.get('Host', '')}").hostname
        return _is_loopback_host(host)

    @staticmethod
    def _string(payload: dict[str, Any], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"{name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _number(payload: dict[str, Any], name: str, default: float) -> float:
        value = float(payload.get(name, default))
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value

    @staticmethod
    def _optional_normalized_speed(
        payload: dict[str, Any], name: str
    ) -> float | None:
        if name not in payload:
            return None
        raw = payload[name]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError(f"{name} must be a number between 0 and 1")
        value = float(raw)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be finite and between 0 and 1")
        return value

    @staticmethod
    def _boolean(payload: dict[str, Any], name: str, default: bool) -> bool:
        value = payload.get(name, default)
        if not isinstance(value, bool):
            raise TypeError(f"{name} must be a boolean")
        return value

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)


def build_runtime(
    config_path: Path,
    socket_path: Path,
    *,
    use_llm: bool | None = None,
) -> RobotRuntime:
    store = ConfigStore(config_path)
    model_config = store.section("language_model")
    planner_config = store.section("planner_model")
    enabled = bool(model_config.get("enabled", False)) if use_llm is None else use_llm
    planner_enabled = bool(planner_config.get("enabled", False))
    if use_llm is False:
        planner_enabled = False
    language_model = None
    planner_model = None
    if enabled:
        language_model = LlamaCppProvider.from_config(model_config)
    if planner_enabled:
        planner_model = LlamaCppProvider.from_config(planner_config)
    return RobotRuntime(
        config_path,
        MujocoSocketBackend(socket_path),
        language_model=language_model,
        planner_model=planner_model,
    )


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> None:
    default_config = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else FALLBACK_CONFIG
    parser = argparse.ArgumentParser(description="Parcel browser control and text-voice panel")
    parser.add_argument("--config", default=str(default_config))
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    llm = parser.add_mutually_exclusive_group()
    llm.add_argument("--llm", action="store_true", help="require the configured LLM")
    llm.add_argument("--no-llm", action="store_true", help="use deterministic commands only")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--browser-path",
        choices=("/", "/poses", "/poses?autoplay=1", "/viewer", "/latency", "/evals"),
        default="/",
        help="local panel page to open after startup",
    )
    parser.add_argument(
        "--pose-review",
        action="store_true",
        help="enable the simulator-only bounded pose/trajectory gallery",
    )
    args = parser.parse_args()

    if not _is_loopback_host(args.host):
        parser.error("--host must be a loopback address; remote control requires authentication")
    if args.browser_path.startswith("/poses") and not args.pose_review:
        parser.error("/poses requires --pose-review")
    if args.pose_review and args.browser_path == "/":
        args.browser_path = "/poses"

    use_llm = True if args.llm else False if args.no_llm else None
    runtime = build_runtime(Path(args.config), Path(args.socket), use_llm=use_llm)
    server = RuntimeHTTPServer(
        (args.host, args.port),
        runtime,
        scene_path=resolve_viewer_scene(Path(args.config)),
        pose_review_enabled=args.pose_review,
    )
    runtime.start()
    url = f"http://{args.host}:{args.port}"
    browser_url = f"{url}{args.browser_path}"
    print(f"Parcel control deck: {url}", flush=True)
    if args.browser_path != "/":
        print(f"Parcel startup page: {browser_url}", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(browser_url)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        runtime.close()


if __name__ == "__main__":
    main()
