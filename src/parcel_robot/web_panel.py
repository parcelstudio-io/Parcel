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

from parcel_robot.backends.mujoco import MujocoSocketBackend
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

#: Card R7 §A. The browser audio gateway's single endpoint. It is a GET that
#: never returns a body: the handler upgrades the connection to a WebSocket and
#: hands the raw socket to ``realtime.audio_gateway``. Kept on the panel's own
#: port and origin deliberately — the loopback Host check, the same-origin check
#: and the per-process CSRF token are already the panel's, and a second listener
#: would have been a second, weaker front door.
REALTIME_AUDIO_PATH = "/api/realtime/audio"

# ---- CARD HW-MIC array-arm-route (scrum/20260822/task_44) ------------------
#
# ONE ARM AT A TIME, ACROSS THE WHOLE PROCESS (verifier finding F1, reproduced
# on the real array). `ThreadingHTTPServer` gives every request its own thread,
# and `ArrayAudioGateway.set_mic` is not re-entrant: it reads `_mic_open` under
# its lock, then opens the duplex pair and calls the runtime's mic gesture
# OUTSIDE it, and only then writes `_mic_open = True`. Two POSTs inside that
# window — one double-click on the panel button — end one of two ways, and both
# are bad: a device that accepts a second open leaks a second input stream and
# a second reader thread, and a device that does not (this array's exclusive
# `hw:` node) refuses the second caller, whose `except ArrayDeviceError` arm
# then writes `_mic_open = False` OVER the first caller's armed state. What the
# owner gets is the worst shape available: both endpoints running, the hosted
# session open and billing, the panel saying "Listening", and every captured
# frame dropped as unarmed. A deaf, paid-for ear from one extra click.
#
# This lock makes the route the serial door the gateway assumes it already has.
# The second caller waits, then finds `_mic_open` true and is answered 200 with
# the state that holds — never a 503 that clobbers a live ear. It is held only
# around `set_mic`, so it can never be held while this handler talks to a
# socket, and nothing under `set_mic` ever calls back into the panel.
#
# It is deliberately process-wide rather than per-server or per-gateway: there
# is one array on a machine, and two panels in one process sharing one lock is
# strictly safer than two panels racing for one sound card. The gateway itself
# should also carry an "opening" state under its own lock — that is HW-4's file
# and this card's handoff, not a second copy of the rule written here.
_ARRAY_MIC_ROUTE_LOCK = threading.Lock()
# ---- END CARD HW-MIC --------------------------------------------------------

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
        # Card R1.6. The realtime lane's arming gate wants "an authenticated
        # handshake token", and the only token in this process is minted right
        # above — after the runtime was built, which is why the runtime cannot
        # read it and must be handed it. Without this line the lane refuses to
        # arm (`no_handshake_token`), which is the correct answer for a runtime
        # with no panel; a lane that invented its own token would be arming on
        # nothing at all.
        bind = getattr(runtime, "bind_panel_token", None)
        if callable(bind):
            bind(self.csrf_token)
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
        if path == REALTIME_AUDIO_PATH:
            self._serve_realtime_audio()
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
            if path == "/api/realtime/text":
                # Card R1.6 §C. The LIVE hosted session, not the local agent:
                # deliberately a separate route from /api/voice/text, which
                # refuses the realtime origin outright (binding constraint 1).
                self._send_json(
                    self.server.runtime.submit_realtime_text(self._string(payload, "text")),
                    HTTPStatus.ACCEPTED,
                )
                return
            # ---- CARD HW-MIC array-arm-route (scrum/20260822/task_44) --------
            #
            # THE DOOR THE ARRAY EAR DID NOT HAVE. Until this route, the only
            # thing in the whole product that ever called `set_mic(True)` was
            # `BrowserAudioGateway`'s own websocket control frame, reached
            # through `_serve_realtime_audio` below — which serves the browser
            # gateway and refuses everything else. So a runtime booted with
            # `audio: {gateway: array}` (card HW-4) constructed the array
            # gateway, probed it, said out loud what it found, and then never
            # listened: no ear, no hosted session, and therefore no mouth
            # either, because opening the microphone is what opens the session
            # (`RobotRuntime._realtime_mic_gesture`).
            #
            # A POST and not a socket, because in array mode the owner's audio
            # never crosses this wire: the PCM goes device -> gateway -> lane
            # inside the runtime's own process, and the only thing the browser
            # has left to say is "arm" or "disarm". It stands behind the same
            # `_authorize_post()` as every other control POST — loopback Host,
            # JSON body, the per-process CSRF token, same origin — and adds no
            # authority of its own.
            #
            # WHAT THIS ROUTE MUST NOT DO IS ORDER ANYTHING. `set_mic` opens the
            # device BEFORE it asks the runtime for the gesture (HW-4 finding
            # F5), so that a device refusal can never leave a billed hosted
            # session open with nothing listening. Any ordering written here
            # would be a second copy of that rule, free to disagree with it.
            if path == "/api/realtime/mic":
                # Strict, not truthy: `{"open": "no"}` and `{"open": 0}` are the
                # shapes that would arm an ear the owner asked to shut.
                if not isinstance(payload.get("open"), bool):
                    raise TypeError("open must be a boolean")
                want_open = bool(payload["open"])
                gateway = getattr(self.server.runtime, "realtime_gateway", None)
                if gateway is None:
                    config = getattr(self.server.runtime, "realtime_config", None)
                    mode = getattr(config, "mode", "unknown")
                    self._send_json(
                        {
                            "detail": (
                                "no realtime audio gateway is constructed, so there is "
                                f"no ear to arm (realtime mode is {mode!r})"
                            ),
                            "kind": None,
                        },
                        HTTPStatus.NOT_FOUND,
                    )
                    return
                # Imported here, not at module scope: `audio_gateway` imports
                # `websockets`, an optional dependency, and a build without it
                # must still serve the whole panel. Reaching this line means a
                # gateway object exists, so the module is already imported.
                from parcel_robot.realtime.audio_gateway import (
                    AUDIO_GATEWAY_ARRAY,
                    ArrayDeviceError,
                )

                snapshot = getattr(gateway, "snapshot", None)
                kind = str(snapshot().get("kind", "")) if callable(snapshot) else ""
                if kind != AUDIO_GATEWAY_ARRAY:
                    self._send_json(
                        {
                            "detail": (
                                f"the fitted ear is {kind or 'unknown'}, not the array: a "
                                f"browser microphone is armed over the WebSocket at "
                                f"{REALTIME_AUDIO_PATH}, not through this route"
                            ),
                            "kind": kind,
                        },
                        HTTPStatus.CONFLICT,
                    )
                    return
                try:
                    # The whole call, not just the open: a close racing an open
                    # is the same corruption with the operands swapped.
                    with _ARRAY_MIC_ROUTE_LOCK:
                        now_open = bool(gateway.set_mic(want_open))
                except ArrayDeviceError as error:
                    # 503 and not 409: the door is right, the microphone behind
                    # it is missing or refusing. The gateway's own text names
                    # the USB id, `scripts/env-audio.sh` and the udev rule, and
                    # it is passed through verbatim rather than summarised.
                    self._send_json(
                        {"detail": str(error), "kind": kind},
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                # The state that NOW HOLDS, which is not always what was asked
                # for: a runtime that refuses the gesture leaves `set_mic`
                # returning False with the streams closed again, and saying
                # `{"open": false}` is the honest report of that.
                self._send_json({"open": now_open, "kind": kind})
                return
            # ---- END CARD HW-MIC --------------------------------------------
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

    # ------------------------------------------------- card R7: audio gateway
    def _serve_realtime_audio(self) -> None:
        """Upgrade this GET to the browser audio websocket, or refuse in HTTP.

        Three gates before a single byte of audio moves, in this order, and all
        three are the panel's existing ones rather than new inventions:

        * **loopback Host** — the same ``_valid_host`` every other route uses;
        * **same origin** — mandatory here in a way it is not for POST, because
          a WebSocket handshake is exempt from CORS: any page on the machine
          could otherwise open this socket. An absent ``Origin`` is a non-browser
          client (the headless proof client), which the loopback + token gates
          already cover;
        * **the panel token** — carried as a second offered subprotocol, because
          a browser cannot set a header on a handshake and a query parameter
          would be printed by ``log_message``. The comparison happens inside the
          gateway, constant-time, against the token this server minted.

        A runtime with no gateway (``mode: text``, or the lane not constructed)
        answers 404: the endpoint does not exist rather than existing and idling.
        """

        # Imported here, not at module scope: ``websockets`` is an optional
        # dependency and a build without it must still serve the whole panel.
        from websockets.datastructures import Headers
        from websockets.http11 import Request

        from parcel_robot.realtime.audio_gateway import (
            BrowserAudioGateway,
            serve_websocket,
        )

        if not self._valid_host():
            self._send_json({"detail": "invalid Host header"}, HTTPStatus.FORBIDDEN)
            return
        gateway = getattr(self.server.runtime, "realtime_gateway", None)
        if not isinstance(gateway, BrowserAudioGateway):
            # ---- CARD HW-MIC (scrum/20260822/task_44): the same refusal, said
            # truthfully. "mode is not audio" became false the day card HW-4
            # landed: in array mode the gateway IS constructed and the runtime
            # IS in `mode: audio` — the ear is simply a different one, armed by
            # POST /api/realtime/mic above. The CONDITION is untouched; this
            # socket still serves the browser ear and only the browser ear.
            snapshot = getattr(gateway, "snapshot", None)
            fitted = str(snapshot().get("kind", "")) if callable(snapshot) else ""
            self._send_json(
                {
                    "detail": (
                        "this socket is the browser ear's door and the fitted ear is "
                        f"{fitted or 'none'}: an array ear is armed with POST "
                        "/api/realtime/mic, and a runtime with no gateway (mode: text) "
                        "has no ear to arm at all"
                    ),
                    "kind": fitted or None,
                },
                HTTPStatus.NOT_FOUND,
            )
            # ---- END CARD HW-MIC ------------------------------------------------
            return
        if "websocket" not in self.headers.get("Upgrade", "").lower():
            self._send_json(
                {"detail": "this endpoint requires a WebSocket upgrade"},
                HTTPStatus.UPGRADE_REQUIRED,
            )
            return
        origin = self.headers.get("Origin")
        if origin and not self._same_origin(origin):
            self._send_json(
                {"detail": "cross-origin audio sockets are forbidden"}, HTTPStatus.FORBIDDEN
            )
            return

        # From here the socket stops being HTTP. Nothing may write to it through
        # BaseHTTPRequestHandler again, which is what ``close_connection`` says.
        self.close_connection = True
        headers = Headers()
        for name, value in self.headers.items():
            headers[name] = value
        request = Request(self.path, headers)
        try:
            serve_websocket(gateway, self.connection, request)
        except (OSError, RuntimeError, ValueError) as error:  # pragma: no cover - defensive
            print(f"parcel-panel: audio gateway socket ended: {error}")

    def _same_origin(self, origin: str) -> bool:
        origin_url = urlsplit(origin)
        host_url = urlsplit(f"http://{self.headers.get('Host', '')}")
        origin_port = origin_url.port or (443 if origin_url.scheme == "https" else 80)
        host_port = host_url.port or 80
        return (
            origin_url.scheme in {"http", "https"}
            and origin_url.hostname == host_url.hostname
            and origin_port == host_port
        )

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
        if origin and not self._same_origin(origin):
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


# ---- CARD TRUTH-1: the planner section's spelling guard, at the read site ----
#
# `config.OVERLAY_INTRODUCIBLE_KEYS` now carries `planner_model`, which is what
# makes the block writable at all (CAP-1's carried finding: `build_runtime` read
# a section the SHA-locked base omits and no overlay could introduce, so the
# planner could never be turned on). That exemption covers the WHOLE SUBTREE —
# the overlay loader stops descending at an exempt parent — so `check_overlay_keys`
# will merge `plan_timeoutt: 5` without a word. Every introducible family in this
# project answers that the same way, by refusing an unknown key WHERE THE SECTION
# IS READ: `CameraStreamConfig.from_section` for the camera family,
# `RobotRuntime.roam_config` for roam, and this for the planner.
#
# Without it the failure is the `minimum_confidenc` failure verbatim: the file on
# disk says `plan_timeoutt: 5`, the provider is built at the shipped 90 s, and
# nothing anywhere says the operator's edit did nothing.
#: Every key `LlamaCppProvider.from_config` reads, plus `enabled`, which
#: `build_runtime` reads itself. Derived from that classmethod's own
#: `config.get(...)` calls and pinned against them by
#: `tests/test_truth1_texts.py`, so a new provider knob cannot make this guard
#: start refusing a legitimate key.
_PLANNER_MODEL_KEYS: frozenset[str] = frozenset(
    {
        "enabled",
        "base_url",
        "model",
        "timeout",
        "streaming",
        "temperature",
        "top_p",
        "context_messages",
        "context_char_budget",
        "max_tokens",
        "enable_thinking",
        "plan_timeout",
        "plan_max_tokens",
        "plan_enable_thinking",
        "plan_temperature",
        "max_stream_events",
        "max_response_bytes",
    }
)


def _check_planner_model_section(section: Any) -> dict[str, Any]:
    """Refuse an unknown ``planner_model:`` key BY NAME. Card TRUTH-1.

    Returns the section as a plain dict. A non-mapping (or an absent section,
    which :meth:`ConfigStore.section` returns as ``{}``) is not an error here —
    it is the default, no-planner case — but a mapping with a key nothing reads
    is, because merging it changes nothing and the setting silently keeps its
    shipped value.
    """

    if not isinstance(section, dict):
        return {}
    unknown = sorted(str(key) for key in section if str(key) not in _PLANNER_MODEL_KEYS)
    if unknown:
        raise ValueError(
            f"unknown planner_model config key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(_PLANNER_MODEL_KEYS))}"
        )
    return dict(section)


# ---- END CARD TRUTH-1 -------------------------------------------------------


# ---- CARD HW-2 go2-backend (scrum/20260822/task_40) ------------------------
#
# WHICH EYE: A MUJOCO SOCKET, OR THE DOG?
#
# `MujocoSocketBackend` is the only `SimulatorBackend` in the tree and
# `observe()` is the runtime's ONE source of pose, scan and obstacle facts
# (wave-3 design §4 row S1). On the Orin there is no MuJoCo — by construction,
# design §3 — so without a branch here nothing starts on the robot at all.
#
# `backend:` is absent from the SHA-locked `configs/robot.yaml`, so with no
# profile `_resolve_backend` returns None and the call below constructs
# byte-for-byte what it constructed before this card existed. That identity is
# asserted through THIS function in `tests/test_hw2_go2_backend.py`, not
# through a stub.
#
# INERT UNTIL HW-5, said plainly (HW-3's finding F4 is this same shape): an
# overlay cannot INTRODUCE a `backend:` block until `"backend"` is in
# `config.OVERLAY_INTRODUCIBLE_KEYS` — ONE entry, exempting the whole subtree,
# because listing the children would look like a spelling guard and be inert
# (ROAM-1 finding 6). That entry and `configs/profiles/go2_edu_plus.yaml` are
# card HW-5's. The spelling guard for this family lives HERE instead, at the
# read site, which is TRUTH-1's rule and the reason `_check_planner_model_section`
# is called above rather than trusted to the loader.

#: Every key `_build_backend` reads. A key outside this set is a typo, and a
#: typo that merges silently leaves the setting at its shipped value while the
#: file on disk says otherwise — the defect the overlay loader exists for.
_BACKEND_KEYS = frozenset(
    {
        "kind",
        "fixture",
        "band",
        "livox",
        "interface",
        "domain_id",
        "session_epoch",
        "max_frames_per_drain",
        "drain_budget_s",
    }
)

#: `backend.livox:` — where the Mid-360 sends its point stream, and therefore
#: what the live source binds. Added under verification (finding F3): the class
#: docstring declared a "bound UDP socket" while nothing on the product path
#: passed one, so `drain()` returned `()` for ever and box-day would have been
#: asked to prove code that did not exist. The VALUE is a box-day measurement
#: (design §8 Q-wire, host 192.168.1.5x); the code that consumes it is not.
#: `port` defaults to HW-3's `HOST_POINT_DATA_PORT`.
_BACKEND_LIVOX_KEYS = frozenset({"host", "port"})

#: The kinds this launcher can construct. Named in the refusal so an operator
#: reads the vocabulary instead of guessing at it.
_BACKEND_KINDS = ("mujoco", "go2")


def _build_backend(section: Any, socket_path: Path) -> Any:
    """The `backend:` section -> a `SimulatorBackend`. Refuses a typo BY NAME."""

    if not isinstance(section, dict) or not section:
        return MujocoSocketBackend(socket_path)
    unknown = sorted(str(key) for key in section if str(key) not in _BACKEND_KEYS)
    if unknown:
        raise ValueError(
            f"unknown backend config key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(_BACKEND_KEYS))}"
        )
    kind = str(section.get("kind", "mujoco"))
    if kind == "mujoco":
        return MujocoSocketBackend(socket_path)
    if kind != "go2":
        raise ValueError(
            f"unknown backend kind {kind!r}; this launcher builds: "
            f"{', '.join(_BACKEND_KINDS)}"
        )

    # Imported HERE, not at module scope: `backends.go2` is cheap and vendor-free,
    # but the import still names exactly where the physical branch begins.
    from parcel_robot.backends.go2 import (
        Go2Backend,
        LiveGo2Sources,
        RecordedStage0Source,
        band_profile_from_config,
    )

    livox = section.get("livox")
    if livox is not None:
        if not isinstance(livox, dict):
            raise TypeError("backend.livox must be a mapping")
        unknown_livox = sorted(
            str(key) for key in livox if str(key) not in _BACKEND_LIVOX_KEYS
        )
        if unknown_livox:
            raise ValueError(
                f"unknown backend.livox key(s): {', '.join(unknown_livox)}; "
                f"allowed: {', '.join(sorted(_BACKEND_LIVOX_KEYS))}"
            )
    livox = livox or {}

    fixture = section.get("fixture")
    if fixture:
        if livox:
            raise ValueError(
                "backend.fixture and backend.livox are two different sensors: a "
                "recording and a Mid-360. Set one."
            )
        # A RECORDING. The source declares REPLAY because it reads a file, so a
        # replayed scan does NOT acquire physical authority at the health join —
        # it latches under a physical requirements table, which is the correct
        # answer and what the desktop measures.
        source: Any = RecordedStage0Source(Path(str(fixture)))
    else:
        # THE DOG. Refuses on a host without the vendor SDK, naming the venv.
        source = LiveGo2Sources(
            interface=str(section.get("interface", "")),
            domain_id=int(section.get("domain_id", 0)),
            livox_host=str(livox.get("host", "")),
            livox_port=int(livox.get("port", 0)),
            max_frames_per_drain=int(section.get("max_frames_per_drain", 32)),
            drain_budget_s=float(
                section.get("drain_budget_s", LiveGo2Sources.DEFAULT_DRAIN_BUDGET_S)
            ),
        )
    return Go2Backend(
        source,
        band_profile=band_profile_from_config(section.get("band")),
        session_epoch=str(section.get("session_epoch", "")),
    )


# ---- END CARD HW-2 go2-backend ----------------------------------------------


def build_runtime(
    config_path: Path,
    socket_path: Path,
    *,
    use_llm: bool | None = None,
) -> RobotRuntime:
    store = ConfigStore(config_path)
    model_config = store.section("language_model")
    # ---- CARD TRUTH-1: the planner section's read site --------------------
    # `config.OVERLAY_INTRODUCIBLE_KEYS` exempts the whole `planner_model`
    # subtree, so the overlay loader will merge a typo inside it without a
    # word. THIS CALL is the guard — not the function alone, which is why
    # `tests/test_truth1_texts.py` pins `build_runtime` itself and not only
    # `_check_planner_model_section`. Delete this call and a misspelled key
    # boots at the shipped default in silence.
    planner_config = _check_planner_model_section(store.section("planner_model"))
    # ---- END CARD TRUTH-1 -------------------------------------------------
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
        # ---- CARD HW-2 go2-backend (task_40): the one branch ----
        _build_backend(store.section("backend"), socket_path),
        # ---- END CARD HW-2 ----
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
