"""Minimal isolated HTTP server for sesame/csm-1b.

Run this from its own Python 3.10 CUDA environment; do not import it from ROS.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import torch
from transformers import AutoProcessor, CsmForConditionalGeneration

MODEL_ID = os.environ.get("CSM_MODEL_ID", "sesame/csm-1b")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
PROCESSOR = AutoProcessor.from_pretrained(MODEL_ID)
MODEL = CsmForConditionalGeneration.from_pretrained(MODEL_ID, device_map=DEVICE)
MODEL_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._send_json({"status": "ok", "model": MODEL_ID, "device": DEVICE})

    def do_POST(self) -> None:
        if self.path != "/synthesize":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            text = str(payload["text"]).strip()
            speaker = int(payload.get("speaker", 0))
            if not text or len(text) > 1000 or not 0 <= speaker <= 9:
                raise ValueError("invalid text or speaker")
            inputs = PROCESSOR(
                f"[{speaker}]{text}", add_special_tokens=True, return_tensors="pt"
            ).to(DEVICE)
            with MODEL_LOCK, torch.inference_mode():
                audio = MODEL.generate(**inputs, output_audio=True)
            with tempfile.TemporaryDirectory(prefix="parcel-csm-") as directory:
                output = Path(directory) / "speech.wav"
                PROCESSOR.save_audio(audio, output)
                wav = output.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.end_headers()
            self.wfile.write(wav)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
        except Exception as error:  # noqa: BLE001 - isolate inference failures from server lifetime
            self._send_json({"error": f"synthesis failed: {error}"}, status=500)

    def log_message(self, format: str, *args: object) -> None:
        print(f"csm-server: {format % args}")

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    host = os.environ.get("CSM_HOST", "127.0.0.1")
    port = int(os.environ.get("CSM_PORT", "8090"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
