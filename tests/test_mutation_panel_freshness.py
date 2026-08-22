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

Card E7 (2026-08-10) added the third one, and it is the one that would have
caught this class a batch earlier. The two tests above are *both* satisfiable by
a stale file: the fast one only reads the committed payload, and the live one is
``@pytest.mark.slow``, so the commit tier never ran it. The committed payload
went a whole batch out of date — recording ``no_false_arrival: true`` while a
live run on the same tree said ``false`` — and ``scripts/ci_gate.py``'s HARD
``hard-safety`` gate kept certifying "no false arrival" from it.
:func:`test_committed_panel_safety_fields_still_reproduce` closes that: it is
cheap enough (one clean run, no mutants) to sit in the commit tier, and it
compares the committed *safety-relevant* fields against a live re-derivation.
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

#: The panel's six original defects. A FLOOR, not an expectation: card VS-6
#: (2026-08-11) appends a seventh (``phantom_view_consistent``) and the panel is
#: meant to keep growing, so pinning the exact count would turn every new
#: mutant into a red build here — the opposite of what this file guards. What
#: still cannot happen is a mutant DISAPPEARING, or one that is exercised but
#: not killed: the assertion below is "every mutant in the payload was killed,
#: and there are at least the original six".
_MINIMUM_KILLED = 6


def _assert_panel_payload_is_current_and_sensitive(payload: dict) -> None:
    assert payload["episode_set_version"] == _CURRENT_FROZEN_EPISODE_SET, (
        "mutation panel certifies "
        f"{payload['episode_set_version']!r} but the current frozen baseline is "
        f"{_CURRENT_FROZEN_EPISODE_SET!r} — bump scripts/mutation_panel.py"
    )
    assert payload["passed"] is True
    killed = [m for m in payload["mutants"] if m["verdict"] == "killed"]
    assert len(killed) == len(payload["mutants"]) >= _MINIMUM_KILLED, (
        f"expected every mutant killed and at least {_MINIMUM_KILLED} of them, "
        f"got {len(killed)}/{len(payload['mutants'])}: "
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


@pytest.mark.slow  # card P0-E: mutation-panel freshness is a nightly evidence ratchet
def test_committed_mutation_panel_is_on_the_current_frozen_set() -> None:
    """The committed payload cannot silently rot to a retired episode set (fast)."""

    payload = json.loads(PANEL_JSON.read_text(encoding="utf-8"))
    _assert_panel_payload_is_current_and_sensitive(payload)


@pytest.mark.slow  # card P0-E: mutation-panel freshness is a nightly evidence ratchet
def test_committed_panel_safety_fields_still_reproduce() -> None:
    """The GATED artifact's safety-relevant fields must survive a live re-run.

    ``scripts/ci_gate.py``'s hard-safety gate reads ``clean_checks`` out of the
    committed payload and prints it as a safety certification. An artifact that
    a live run contradicts is therefore not merely out of date — it is the gate
    asserting something untrue. One clean run (~4 s), no mutants, so this can
    live in the commit tier where the slow whole-panel test cannot.

    A red here is NOT a licence to regenerate the artifact: the artifact is a
    gated input, and the honest response is to diagnose why the tree stopped
    reproducing it.
    """

    from scripts.mutation_panel import clean_safety_fields, live_clean_safety_fields

    committed = clean_safety_fields(json.loads(PANEL_JSON.read_text(encoding="utf-8")))
    live = live_clean_safety_fields()
    assert live == committed, (
        "the committed mutation panel no longer reproduces its own safety-relevant "
        f"fields on this tree: committed={committed} live={live} — the hard-safety "
        "gate must not certify from it until the divergence is diagnosed"
    )


@pytest.mark.slow
def test_mutation_panel_runs_on_the_current_frozen_set_live() -> None:
    """Re-run the panel live: the panel CODE must be on the current set too."""

    from scripts.mutation_panel import run_panel

    payload = run_panel()
    _assert_panel_payload_is_current_and_sensitive(payload)
