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
MAX_REQUEST_BYTES = 65_536


class RuntimeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], runtime: RobotRuntime):
        self.runtime = runtime
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
        if path == "/api/state":
            self._send_json(self.server.runtime.snapshot())
            return
        if path == "/api/health":
            self._send_json({"status": "ok"})
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
            if path == "/api/owner":
                message = self.server.runtime.move_owner(
                    self._number(payload, "dx", 0.0),
                    self._number(payload, "dy", 0.0),
                )
                self._send_json({"message": message})
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
    enabled = bool(model_config.get("enabled", False)) if use_llm is None else use_llm
    language_model = None
    if enabled:
        language_model = LlamaCppProvider(
            base_url=str(model_config.get("base_url", "http://127.0.0.1:8080")),
            model=str(model_config.get("model", "gemma")),
            timeout=float(model_config.get("timeout", 30)),
        )
    return RobotRuntime(
        config_path,
        MujocoSocketBackend(socket_path),
        language_model=language_model,
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
    args = parser.parse_args()

    if not _is_loopback_host(args.host):
        parser.error("--host must be a loopback address; remote control requires authentication")

    use_llm = True if args.llm else False if args.no_llm else None
    runtime = build_runtime(Path(args.config), Path(args.socket), use_llm=use_llm)
    server = RuntimeHTTPServer((args.host, args.port), runtime)
    runtime.start()
    url = f"http://{args.host}:{args.port}"
    print(f"Parcel control deck: {url}", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
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
