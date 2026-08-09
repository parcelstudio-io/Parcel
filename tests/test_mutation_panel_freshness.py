"""The mutation panel must certify the CURRENT frozen episode set — anti-rot.

Card panel-v3-repin (2026-08-09). The audit found the committed panel certifying
the RETIRED v2 set, where its strongest check (``no_false_arrival``) was silently
disabled because the v2 clean run itself contained a false arrival — a surviving
mutant would have been missed on exactly the code path v3 changed. These tests
make that class of rot loud: the committed payload AND a live run must both be on
the newest frozen ``vN`` episode set, pass 6/6, and keep ``no_false_arrival``
live (green on the clean run AND actually reddened by a mutant, not merely
absent). When a v4 is frozen, ``_CURRENT_FROZEN_EPISODE_SET`` advances on its own
and both tests fail until ``scripts/mutation_panel.py`` is bumped with it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from evals.nav_instruct.generator import EPISODE_SETS

REPO = Path(__file__).resolve().parents[1]
PANEL_JSON = REPO / "evals" / "nav_instruct" / "results" / "mutation_panel.json"

#: The newest frozen baseline episode set: the highest plain ``vN`` version
#: (``v1a-scene-truth-only`` and other suffixed sets are not baselines). Advances
#: automatically when a ``v4`` freeze is added, so a panel left on an older set
#: reddens here instead of silently certifying a retired set.
_CURRENT_FROZEN_EPISODE_SET = max(
    (version for version in EPISODE_SETS if re.fullmatch(r"v\d+", version)),
    key=lambda version: int(version[1:]),
)

_EXPECTED_KILLED = 6


def _assert_panel_payload_is_current_and_sensitive(payload: dict) -> None:
    assert payload["episode_set_version"] == _CURRENT_FROZEN_EPISODE_SET, (
        "mutation panel certifies "
        f"{payload['episode_set_version']!r} but the current frozen baseline is "
        f"{_CURRENT_FROZEN_EPISODE_SET!r} — bump scripts/mutation_panel.py"
    )
    assert payload["passed"] is True
    killed = [m for m in payload["mutants"] if m["verdict"] == "killed"]
    assert len(killed) == _EXPECTED_KILLED, (
        f"expected {_EXPECTED_KILLED} killed mutants, got {len(killed)}: "
        f"{[(m['mutation'], m['verdict']) for m in payload['mutants']]}"
    )
    # The no_false_arrival channel must be LIVE: green on the clean run (so a
    # mutant CAN redden it — the v2 rot was that the clean run was already red
    # here) AND actually reddened by at least one mutant (so it is exercised, not
    # merely dormant on this episode subset).
    assert payload["clean_checks"]["no_false_arrival"] is True, (
        "no_false_arrival is disabled on the clean run — the exact v2 rot this "
        "card removed; a false arrival in the clean run silently disables the "
        "panel's strongest check"
    )
    assert any(
        "no_false_arrival" in mutant["checks_reddened"] for mutant in payload["mutants"]
    ), "no_false_arrival is green on the clean run but no mutant exercises it"


def test_committed_mutation_panel_is_on_the_current_frozen_set() -> None:
    """The committed payload cannot silently rot to a retired episode set (fast)."""

    payload = json.loads(PANEL_JSON.read_text(encoding="utf-8"))
    _assert_panel_payload_is_current_and_sensitive(payload)


@pytest.mark.slow
def test_mutation_panel_runs_on_the_current_frozen_set_live() -> None:
    """Re-run the panel live: the panel CODE must be on the current set too."""

    from scripts.mutation_panel import run_panel

    payload = run_panel()
    _assert_panel_payload_is_current_and_sensitive(payload)
