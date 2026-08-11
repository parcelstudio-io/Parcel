"""Lane E4 seams: latency-ledger reachability, tier registry, runner flag opt-in.

Each test here pins a *correction* Fable's independent task_15 audit asked for,
in the narrow way that keeps the correction from silently rotting back:

* the latency ledger must be reachable without an env var, and must refuse to
  admit a turn-less row into the committed ledger (a turn-less row would make
  ci_gate's ratchet compare nothing and pass vacuously);
* "T-cam" must not be readable as a registered perception tier;
* the nav_instruct runner's new flag seam must be a no-op when unused, so every
  frozen row stays reproducible.
"""

from __future__ import annotations

import inspect

import pytest

from evals.nav_instruct.runner import ALLOWED_NAVIGATOR_OVERRIDES, NavInstructRunner
from parcel_robot.detection_adapter.perception_chain import (
    REGISTERED_TIERS,
    PerceptionChain,
)
from parcel_robot.observability import (
    LATENCY_LEDGER_ENV,
    LATENCY_LEDGER_OPT_OUT_ENV,
    LATENCY_LEDGER_RELPATH,
    append_latency_ledger_row,
    default_latency_ledger_path,
    resolve_latency_ledger_path,
)

# --- latency ledger reachability (C-A debt) ---------------------------------


def test_default_ledger_path_is_the_committed_repo_ledger() -> None:
    default = default_latency_ledger_path()
    assert default is not None
    assert default.as_posix().endswith(LATENCY_LEDGER_RELPATH)


def test_resolution_prefers_explicit_then_env_then_repo_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv(LATENCY_LEDGER_OPT_OUT_ENV, raising=False)

    explicit = tmp_path / "explicit.jsonl"
    monkeypatch.setenv(LATENCY_LEDGER_ENV, str(tmp_path / "from-env.jsonl"))
    assert resolve_latency_ledger_path(explicit) == explicit
    assert resolve_latency_ledger_path() == tmp_path / "from-env.jsonl"

    monkeypatch.delenv(LATENCY_LEDGER_ENV, raising=False)
    assert resolve_latency_ledger_path() == default_latency_ledger_path()


def test_opt_out_env_restores_the_write_nothing_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv(LATENCY_LEDGER_ENV, raising=False)
    monkeypatch.setenv(LATENCY_LEDGER_OPT_OUT_ENV, "1")
    assert resolve_latency_ledger_path() is None


def test_a_pytest_process_never_resolves_the_committed_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A unit test's teardown is not a measurement and must not mutate it."""

    monkeypatch.delenv(LATENCY_LEDGER_ENV, raising=False)
    monkeypatch.delenv(LATENCY_LEDGER_OPT_OUT_ENV, raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "sentinel")
    assert resolve_latency_ledger_path() is None


def test_turnless_row_is_refused_by_the_committed_ledger() -> None:
    default = default_latency_ledger_path()
    assert default is not None
    before = default.read_bytes() if default.exists() else b""
    assert append_latency_ledger_row({"turns": 0, "metrics": {}}, default) is None
    after = default.read_bytes() if default.exists() else b""
    assert after == before, "a turn-less row must never reach the committed ledger"


def test_turnless_row_is_still_written_to_an_explicitly_chosen_path(tmp_path) -> None:
    target = tmp_path / "chosen.jsonl"
    assert append_latency_ledger_row({"turns": 0}, target) == target
    assert target.read_text(encoding="utf-8").strip()


# --- "T-cam" is a report label, not a tier ----------------------------------


def test_registered_tiers_is_exactly_what_from_tier_can_build() -> None:
    assert REGISTERED_TIERS == ("T0", "T1")
    for name in REGISTERED_TIERS:
        assert PerceptionChain.from_tier(name).tier.name == name


@pytest.mark.parametrize("label", ["T-cam", "T-CAM", "T-cam-proxy-vb-live"])
def test_no_t_cam_tier_exists(label: str) -> None:
    with pytest.raises(ValueError, match="unknown perception tier"):
        PerceptionChain.from_tier(label)


def test_eval_cell_ids_declare_themselves_as_proxies() -> None:
    from evals.nav_instruct.cam_arrival import TIER_ID as ARRIVAL
    from evals.nav_instruct.cam_detector import TIER_ID as DETECTOR
    from evals.nav_instruct.cam_lock_on import TIER_ID as LOCK_ON
    from evals.nav_instruct.cam_multiview_metric import LIVE_TIER_ID
    from evals.nav_instruct.cam_multiview_metric import TIER_ID as PURE

    for tier_id in (ARRIVAL, DETECTOR, LOCK_ON, PURE, LIVE_TIER_ID):
        assert tier_id.startswith("T-cam-proxy-"), tier_id
        assert tier_id not in REGISTERED_TIERS


# --- runner flag seam is a no-op when unused --------------------------------


def test_navigator_overrides_defaults_to_empty_and_is_a_closed_set() -> None:
    """Default is empty, so ``_navigator`` expands ``**{}`` — no keyword at all.

    That is what makes every persisted row reproducible under the new seam: the
    flag-OFF arm makes the byte-identical ``from_config`` call it always made.
    """

    default = inspect.signature(NavInstructRunner.__init__).parameters[
        "navigator_overrides"
    ].default
    assert default is None
    assert ALLOWED_NAVIGATOR_OVERRIDES == frozenset(
        {"value_directed_search", "detection_lock_on"}
    )


def test_unknown_navigator_override_is_refused() -> None:
    with pytest.raises(ValueError, match="pre-registered flags"):
        NavInstructRunner(navigator_overrides={"make_it_pass": True})
