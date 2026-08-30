"""The mutation panel must certify the CURRENT frozen episode set — anti-rot.

Card panel-v3-repin (2026-08-09). The audit found the committed panel certifying
the RETIRED v2 set, where its strongest check (``no_false_arrival``) was silently
disabled because the v2 clean run itself contained a false arrival — a surviving
mutant would have been missed on exactly the code path v3 changed. These tests
make that class of rot loud: the committed payload AND a live run must both be on
the newest frozen ``vN`` episode set, kill every seeded defect, and keep
``no_false_arrival`` plus direct reactive-gate coverage live
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
from collections.abc import Sequence
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
    from scripts.mutation_panel import (
        PANEL_EPISODE_IDS,
        PANEL_MATRIX_DIGEST,
        PANEL_MATRIX_PER_FAMILY,
        PANEL_MATRIX_SEED,
    )

    assert payload["episode_set_version"] == _CURRENT_FROZEN_EPISODE_SET, (
        "mutation panel certifies "
        f"{payload['episode_set_version']!r} but the current frozen baseline is "
        f"{_CURRENT_FROZEN_EPISODE_SET!r} — bump scripts/mutation_panel.py"
    )
    assert payload["passed"] is True
    assert payload["coverage_matrix_seed"] == PANEL_MATRIX_SEED
    assert payload["coverage_matrix_per_family"] == PANEL_MATRIX_PER_FAMILY
    assert payload["coverage_matrix_digest"] == PANEL_MATRIX_DIGEST
    assert payload["episode_ids"] == list(PANEL_EPISODE_IDS), (
        "mutation-panel episode identity/order drifted; the simulator's seeded "
        "scan RNG is deterministic for a campaign but is not reset per episode"
    )
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
    assert payload["clean_checks"]["reactive_gate_exercised"] is True
    clean_coverage = payload["clean_run"]["reactive_gate_coverage"]
    assert clean_coverage["changed_nonzero"] > 0
    reactive = next(
        mutant for mutant in payload["mutants"]
        if mutant["mutation"] == "reactive_gate_disabled"
    )
    assert reactive["verdict"] == "killed"
    assert "reactive_gate_exercised" in reactive["checks_reddened"]
    assert reactive["run"]["reactive_gate_coverage"]["changed_nonzero"] == 0


@pytest.mark.slow  # card P0-E: mutation-panel freshness is a nightly evidence ratchet
def test_committed_mutation_panel_is_on_the_current_frozen_set() -> None:
    """The committed payload cannot silently rot to a retired episode set (fast)."""

    payload = json.loads(PANEL_JSON.read_text(encoding="utf-8"))
    _assert_panel_payload_is_current_and_sensitive(payload)


def _declared_disabled(provenance: str, name: str) -> bool:
    """Does the artifact's own provenance declare ``name`` a disabled channel?"""

    return f"{name} disabled as a kill channel" in provenance


def freshness_failure_message(
    committed: dict,
    live: dict,
    provenance: str,
    *,
    live_survivors: Sequence[str] | None = None,
) -> str | None:
    """``None`` when the artifact still reproduces; otherwise WHY, by DIRECTION.

    Card C0 follow-up F1. The equality below is what forces a re-run, and that
    part is unchanged. What was missing is *direction*, and the directions need
    opposite responses:

    * **a mutant SURVIVED the live run** — the most fundamental failure, and it
      outranks the other two: the selected episodes no longer exercise that
      mutant's code at all, so the panel has stopped being a panel. The
      integrator's F1 addendum found exactly this waiting on the owner's
      ``grid_planner.py``: with that diff the reactive gate is called
      101/88/51/62/0 times across the five panel episodes and zeroes a non-zero
      request **0** times, so ``reactive_gate_disabled`` becomes an equivalent
      mutant. Regenerating cannot fix that — the episode SELECTION has to
      change, and the selection is frozen evidence, so it is the owner's call.

    * **live REDDER than committed** — the tree stopped satisfying something the
      gated artifact certifies. Diagnose the tree; regenerating would launder a
      live defect into a fresh green certificate. This is the original wording,
      kept verbatim.
    * **live GREENER than committed on a channel the provenance declares
      disabled** — the defect that cost the panel a kill channel is FIXED. The
      artifact is now understating the harness, and the declaration it carries
      ("<name> disabled as a kill channel … re-armed when …") has come due. The
      honest response here IS to re-run and withdraw the declaration, and the
      message has to say so, because the red-direction wording would send a
      reader off to diagnose a tree that just got better.

    Pure by construction: a live run is passed IN, so the two directions can be
    pinned with fixture payloads instead of a simulator.
    """

    if live_survivors:
        names = sorted(live_survivors)
        clauses = "; ".join(
            f"the panel episodes no longer exercise {name}'s channel; re-choose "
            "panel episodes on which the gate binds (owner E3 decision)"
            for name in names
        )
        return (
            "the mutation panel did not PASS on this tree: "
            f"{names} survived — " + clauses
        )
    if live == committed:
        return None
    committed_checks = committed.get("clean_checks") or {}
    live_checks = live.get("clean_checks") or {}
    withdrawn = [
        name
        for name, was_green in sorted(committed_checks.items())
        if not was_green and live_checks.get(name) and _declared_disabled(provenance, name)
    ]
    if withdrawn:
        clauses = "; ".join(
            "re-run the panel and withdraw the "
            f"'{name} disabled as a kill channel' declaration"
            for name in withdrawn
        )
        return (
            "the committed mutation panel is STALE IN THE GREEN DIRECTION on "
            f"{withdrawn}: the live clean run now PASSES a check the committed "
            "artifact records red and its own provenance declares disabled, so "
            "the declaration has come due — " + clauses + " "
            f"(committed={committed} live={live})"
        )
    return (
        "the committed mutation panel no longer reproduces its own safety-relevant "
        f"fields on this tree: committed={committed} live={live} — the hard-safety "
        "gate must not certify from it until the divergence is diagnosed"
    )


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
    reproducing it — UNLESS the drift is in the green direction on a channel the
    provenance itself declared disabled, in which case the declaration has come
    due and :func:`freshness_failure_message` says so instead.
    """

    from scripts.mutation_panel import clean_safety_fields, live_clean_safety_fields

    payload = json.loads(PANEL_JSON.read_text(encoding="utf-8"))
    committed = clean_safety_fields(payload)
    live = live_clean_safety_fields()
    problem = freshness_failure_message(
        committed, live, str(payload.get("episode_set_provenance", ""))
    )
    assert problem is None, problem


@pytest.mark.slow
def test_mutation_panel_runs_on_the_current_frozen_set_live() -> None:
    """Re-run the panel live: the panel CODE must be on the current set too."""

    from scripts.mutation_panel import clean_safety_fields, run_panel

    committed_payload = json.loads(PANEL_JSON.read_text(encoding="utf-8"))
    payload = run_panel()
    # F1: say WHY in the panel's own vocabulary before the terse assertions
    # below — a survivor, a green-direction drift that has come due, or a red
    # one — instead of ``assert False is True``.
    problem = freshness_failure_message(
        clean_safety_fields(committed_payload),
        clean_safety_fields(payload),
        str(committed_payload.get("episode_set_provenance", "")),
        live_survivors=[*payload["survivors"], *payload["equivalent_mutants"]],
    )
    assert problem is None, problem
    _assert_panel_payload_is_current_and_sensitive(payload)


#: Clean-run checks that a re-freeze may NEVER trade away. The panel's outcome
#: checks are not equal: ``no_authority_disagreement`` is the one-way
#: ``scorer ⇒ system`` invariant (instrument 5), which a *conservative* system
#: refusal reddens without anything unsafe having happened, so a recorded
#: re-run may carry it red as long as it says so. The other three are floors —
#: a collision, a false arrival, or a teleported trace is never something an
#: artifact gets to normalise.
_UNDISABLEABLE_CLEAN_CHECKS: tuple[str, ...] = (
    "zero_collisions",
    "no_false_arrival",
    "path_length_plausible",
    "reactive_gate_exercised",
)


@pytest.mark.slow  # card C0 (FIX-SUBSTRATE-1): declared-disable ratchet
def test_red_clean_checks_are_declared_disabled_kill_channels() -> None:
    """A red clean check silently disables a kill channel — so it must be declared.

    ``scripts.mutation_panel.run_panel`` credits a mutant only with checks that
    were GREEN on the clean run (``reddened = ... if not green and
    clean_checks.get(key, True)``). A check that is red on the clean run is
    therefore not merely a recorded blemish: it is **switched off as a kill
    channel for every mutant**, exactly the way ``no_false_arrival`` was
    switched off on the retired v2 set — the rot this file exists to make loud.

    The two tests above cannot see that class. They assert ``passed``, the
    kill count, and ``no_false_arrival``; a panel can satisfy all three while
    quietly losing a different channel. This one closes it, without forbidding
    the honest case: card C0's recorded re-run carries
    ``no_authority_disagreement`` red because the navigator *refuses* an
    arrival the scorer grants (the safe direction), and that is allowed — but
    only if the artifact's own provenance names the disabled channel and says
    when it is re-armed. Silence is the failure.
    """

    payload = json.loads(PANEL_JSON.read_text(encoding="utf-8"))
    checks = payload["clean_checks"]
    red = sorted(name for name, green in checks.items() if not green)
    provenance = str(payload.get("episode_set_provenance", ""))

    forbidden = sorted(set(red) & set(_UNDISABLEABLE_CLEAN_CHECKS))
    assert not forbidden, (
        f"the committed panel's clean run is red on {forbidden} — these are "
        "absolute safety floors and may never be carried red by a re-freeze; "
        "diagnose the tree instead of regenerating the artifact"
    )

    for name in red:
        assert f"{name} disabled as a kill channel" in provenance, (
            f"clean check {name!r} is red, which silently disables it as a kill "
            "channel for every mutant, but the artifact's provenance never says "
            f"so — it must contain the phrase '{name} disabled as a kill "
            "channel' together with the condition for re-arming it"
        )

    # A red channel must not also be claimed as a kill: that would mean the
    # payload was assembled by something other than ``run_panel``.
    for mutant in payload["mutants"]:
        overlap = sorted(set(mutant["checks_reddened"]) & set(red))
        assert not overlap, (
            f"mutant {mutant['mutation']!r} claims {overlap} as reddened checks "
            "while the clean run is already red on them — an artifact that did "
            "not come from run_panel"
        )


# --------------------------------------------------------------------------
# card C0 follow-up F1 — both freshness DIRECTIONS, pinned on fixture panels
# --------------------------------------------------------------------------

#: The declaration card C0's recorded re-run wrote into the artifact. The green
#: -direction message exists to tell a reader this line has come due.
_DECLARATION = (
    "no_authority_disagreement disabled as a kill channel from this re-run; "
    "re-armed when D-15 agrees again"
)


def _fields(**checks: bool) -> dict:
    """A ``clean_safety_fields``-shaped payload with every clean floor."""

    base = {
        "zero_collisions": True,
        "no_authority_disagreement": True,
        "no_false_arrival": True,
        "path_length_plausible": True,
        "reactive_gate_exercised": True,
    }
    base.update(checks)
    return {
        "collisions": 0,
        "authority": {"agreement": 5},
        "clean_checks": base,
        "reactive_gate_coverage": {
            "calls": 1,
            "requested_nonzero": 1,
            "changed_nonzero": 1,
            "translation_zeroed": 0,
        },
    }


def test_freshness_message_is_silent_when_the_artifact_still_reproduces() -> None:
    fields = _fields(no_authority_disagreement=False)
    assert freshness_failure_message(fields, dict(fields), _DECLARATION) is None


def test_freshness_message_when_live_is_GREENER_says_withdraw_the_declaration() -> None:
    """The re-arm case: the defect is fixed, so the declaration has come due.

    This is card C0's own future. When the owner's ``grid_planner.py`` lands,
    ``nav-region_goal-D-15`` agrees again and this exact message is what the
    next reader gets — not "diagnose why the tree stopped reproducing it",
    which would point them at a tree that just got better.
    """

    committed = _fields(no_authority_disagreement=False)
    live = _fields(no_authority_disagreement=True)

    message = freshness_failure_message(committed, live, _DECLARATION)

    assert message is not None
    assert message.startswith(
        "the committed mutation panel is STALE IN THE GREEN DIRECTION on "
        "['no_authority_disagreement']: the live clean run now PASSES a check "
        "the committed artifact records red and its own provenance declares "
        "disabled, so the declaration has come due — re-run the panel and "
        "withdraw the 'no_authority_disagreement disabled as a kill channel' "
        "declaration "
    )
    # The exact phrase the integrator's ruling names, verbatim.
    assert (
        "re-run the panel and withdraw the 'no_authority_disagreement disabled "
        "as a kill channel' declaration" in message
    )
    assert "must not certify from it until the divergence is diagnosed" not in message


def test_freshness_message_when_live_is_REDDER_keeps_the_original_wording() -> None:
    """A tree that stopped satisfying the artifact is still a diagnose-first red."""

    committed = _fields()
    live = _fields(no_false_arrival=False)

    message = freshness_failure_message(committed, live, _DECLARATION)

    assert message == (
        "the committed mutation panel no longer reproduces its own safety-relevant "
        f"fields on this tree: committed={committed} live={live} — the hard-safety "
        "gate must not certify from it until the divergence is diagnosed"
    )
    assert "withdraw" not in message


def test_a_green_drift_on_an_UNDECLARED_channel_is_still_a_diagnose_first_red() -> None:
    """Greener is only "come due" where the artifact ADMITTED it was disabled.

    A channel that went from red to green without the provenance ever declaring
    it disabled is an artifact nobody explained, and the reader should be sent
    to diagnose it exactly as before. This is what stops the green branch from
    becoming a blanket licence to regenerate.
    """

    committed = _fields(no_authority_disagreement=False)
    live = _fields(no_authority_disagreement=True)

    message = freshness_failure_message(committed, live, provenance="")

    assert message is not None
    assert "withdraw" not in message
    assert "must not certify from it until the divergence is diagnosed" in message


def test_freshness_message_when_a_mutant_SURVIVES_says_re_choose_the_episodes() -> None:
    """F1 addendum: the owner's `grid_planner.py` makes the reactive gate inert here.

    The integrator measured it on the five panel episodes: with that diff the
    gate is called 101/88/51/62/0 times and zeroes a non-zero request **0**
    times, so ``reactive_gate_disabled`` produces a run identical to the clean
    one and survives. "D-15 agrees again" and "the gate never fires" are the
    same event, so the re-arm cannot be done by regenerating — the episode
    SELECTION has to change, and that is frozen evidence.

    The survivor outranks the direction messages: it is reported even though
    this fixture is ALSO green-direction stale on a declared-disabled channel.
    """

    committed = _fields(no_authority_disagreement=False)
    live = _fields(no_authority_disagreement=True)

    message = freshness_failure_message(
        committed, live, _DECLARATION, live_survivors=["reactive_gate_disabled"]
    )

    assert message == (
        "the mutation panel did not PASS on this tree: "
        "['reactive_gate_disabled'] survived — the panel episodes no longer "
        "exercise reactive_gate_disabled's channel; re-choose panel episodes on "
        "which the gate binds (owner E3 decision)"
    )
    assert "withdraw" not in message


def test_survivors_are_reported_even_when_the_clean_fields_still_reproduce() -> None:
    """A panel can reproduce its clean run perfectly and still have stopped working."""

    fields = _fields()
    message = freshness_failure_message(
        fields, dict(fields), _DECLARATION, live_survivors=["reactive_gate_disabled"]
    )
    assert message is not None and "re-choose panel episodes" in message


def test_no_survivors_leaves_the_direction_logic_untouched() -> None:
    committed = _fields(no_authority_disagreement=False)
    live = _fields(no_authority_disagreement=True)
    for empty in (None, [], ()):
        message = freshness_failure_message(
            committed, live, _DECLARATION, live_survivors=empty
        )
        assert message is not None
        assert "re-run the panel and withdraw the" in message
        assert "re-choose panel episodes" not in message
