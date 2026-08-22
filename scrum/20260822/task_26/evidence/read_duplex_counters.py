"""Card DUPLEX-1, row OG-1. Read the turn-taking counters out of /api/state.

Usage (from the repo root, with the stack running on :8765):

    curl -s localhost:8765/api/state | .parcel/bin/python \
        scrum/20260822/task_26/evidence/read_duplex_counters.py

Committed as a script because the row it serves is spent inside AIR-1's ~1.3 h
owner session: a one-liner that needs its key path debugged at the microphone
is a row that does not get measured. The correction pass found the doc's
original one-liner raised KeyError — it indexed ``["realtime"]`` and then
reached for lane keys that live under ``["realtime"]["lane"]``.
"""

from __future__ import annotations

import json
import sys

FLOOR_KEYS = (
    "backchannel_floor_ms",
    "backchannel_holds",
    "backchannels_survived",
    "barge_ins_committed",
    "backchannel_turns_retracted",
    "turn_decider_disagreements",
)
LANE_DUCK_KEYS = ("ducks_requested", "duck_resumes_requested", "ducks_unsupported")
GATEWAY_KEYS = ("ducks", "duck_resumes", "duck_refusals", "last_duck_gain")


def main() -> int:
    state = json.load(sys.stdin)
    realtime = state.get("realtime") or {}
    lane = realtime.get("lane")
    if not isinstance(lane, dict):
        print("no hosted lane in /api/state — is realtime enabled and a session open?")
        return 2
    gateway = realtime.get("gateway") or {}
    controller = lane.get("turn_controller") or {}

    print(f"state          {controller.get('state')!r}  (ducked={controller.get('ducked')})")
    print(f"owner turn owed {controller.get('owner_turn_owed')}")
    for key in FLOOR_KEYS:
        print(f"{key:<30} {lane.get(key)}")
    for key in LANE_DUCK_KEYS:
        print(f"{key:<30} {lane.get(key)}")
    for key in GATEWAY_KEYS:
        print(f"gateway.{key:<22} {gateway.get(key)}")

    survived = lane.get("backchannels_survived") or 0
    holds = lane.get("backchannel_holds") or 0
    if holds:
        print(f"\nsurvival this session: {survived}/{holds} = {survived / holds:.2f}")
    if lane.get("turn_decider_disagreements"):
        print("\n!! the hold and the turn controller disagreed — see DUPLEX1_STATUS.md finding 2")
    if not lane.get("backchannel_floor_ms"):
        print("\n!! backchannel_floor_ms is 0: the floor is OFF, so nothing here is a DUPLEX-1 row")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
