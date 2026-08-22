"""Card DUPLEX-1, rows OG-2 and OG-4. Read a capture session's cut stamps.

Usage (from the repo root; with no argument it takes the NEWEST session under
the capture root, which is where ``realtime.capture.dir: recordings`` resolves):

    .parcel/bin/python scrum/20260822/task_26/evidence/read_onset_stamps.py
    .parcel/bin/python scrum/20260822/task_26/evidence/read_onset_stamps.py <session-dir>

Prints every interrupted robot segment with MARK-1's ``interrupted_at`` and
DUPLEX-1's ``interrupted_onset_at`` / ``interrupt_hold_ms``, and says whether a
``turns.jsonl`` (RT-TURNS-1) sits beside it.

The correction pass wrote this because the doc's original commands pointed at
``~/recordings/<session>/`` — a path that does not exist. ``capture.dir``
resolves against the REPO ROOT (``realtime/config.resolve_capture_dir``), and
the session directory is named by the evidence session id, not by a date.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path


def capture_root() -> Path:
    """Ask the PRODUCT where captures go, rather than re-deriving it here.

    ``resolve_capture_dir`` resolves a relative ``capture.dir`` against the repo
    root and not against the cwd — the correction pass's own first version of
    this script got that arithmetic wrong by one directory, which is exactly the
    failure the product function exists to prevent.
    """

    from parcel_robot.realtime.config import default_realtime_config, resolve_capture_dir

    configured = "recordings"
    # A reader must not die on a config it cannot load.
    with contextlib.suppress(AttributeError, OSError, TypeError, ValueError):
        capture = getattr(default_realtime_config(), "capture", None)
        configured = getattr(capture, "dir", None) or "recordings"
    return resolve_capture_dir(str(configured))


def newest_session() -> Path | None:
    root = capture_root()
    if not root.is_dir():
        return None
    sessions = [p for p in root.iterdir() if p.is_dir() and (p / "index.json").is_file()]
    if not sessions:
        return None
    return max(sessions, key=lambda p: (p / "index.json").stat().st_mtime)


def main(argv: list[str]) -> int:
    session = Path(argv[1]).expanduser() if len(argv) > 1 else newest_session()
    if session is None:
        print(f"no capture session under {capture_root()} — is realtime.capture enabled?")
        return 2
    index_path = session / "index.json"
    if not index_path.is_file():
        print(f"{index_path} does not exist")
        return 2

    index = json.loads(index_path.read_text(encoding="utf-8"))
    segments = index.get("streams", {}).get("robot", {}).get("segments", [])
    cut = [s for s in segments if s.get("interrupted")]
    print(f"session {session}")
    print(f"  robot segments: {len(segments)}, interrupted: {len(cut)}")
    for segment in cut:
        onset = segment.get("interrupted_onset_at")
        print(
            f"  utterance {segment.get('utterance')}: "
            f"onset={onset or '(none — floor was 0)'} "
            f"cut={segment.get('interrupted_at')} "
            f"hold={segment.get('interrupt_hold_ms')} ms "
            f"byte={segment.get('interrupted_byte')} t={segment.get('interrupted_t_s')} s"
        )
    turns = session / "turns.jsonl"
    if turns.is_file():
        rows = [line for line in turns.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(f"  turns.jsonl: {len(rows)} row(s) — feed it to tools/bargein_through_air.py --turns")
    else:
        print("  turns.jsonl: ABSENT — call runtime.export_realtime_turns() before the stack exits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
