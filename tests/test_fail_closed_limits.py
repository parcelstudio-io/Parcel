"""Card R23 — limits that refuse.

The finding (full audit 2026-08-20, §Safety-2): ``ConfigStore.safety_limits()``
did a bare ``float()`` and ``SafetyLimits`` had no validation, so a NaN velocity
limit silently disabled the clamp at BOTH enforcement sites — ``abs(v) > nan``
is False for every v, in the arbiter and in the SafetySupervisor alike — while
inf, zero and negative were accepted without complaint.

What this module pins, in the order the exposure actually runs:

1. the shipped ``configs/robot.yaml`` still loads, to the same effective
   numbers (it is digest-pinned; validation must not move the frozen baseline);
2. the loader refuses a malformed velocity/accel limit, by name;
3. the dataclass refuses one too, so a direct construction cannot slip past;
4. both comparison sites refuse when handed an unusable limit ANYWAY — the
   layer that holds when 2 and 3 are bypassed;
5. the operator ``--config`` path refuses at launch rather than producing an
   unclamped robot — including the composite that defeated the accidental
   ``ControlLimits`` backstop;
6. the doctrine: every loader in this repo that DOCUMENTS itself fail-closed
   refuses a malformed number, so the next numeric key added without
   validation reddens here.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from parcel_robot import web_panel
from parcel_robot.config import ConfigStore
from parcel_robot.core.arbiter import CommandArbiter
from parcel_robot.core.commands import MotionIntent
from parcel_robot.core.motion_shaping import MotionShapingConfig
from parcel_robot.duplex.config import DuplexConfig
from parcel_robot.models import ToolCall, VelocityCommand
from parcel_robot.navigation.dynamic_layer import TimeToCollisionConfig
from parcel_robot.navigation.follow import FollowPredictionConfig
from parcel_robot.navigation.search_owner import SearchOwnerConfig
from parcel_robot.realtime.config import RealtimeConfigError, realtime_config_from_mapping
from parcel_robot.safety import (
    SafetyLimitError,
    SafetyLimits,
    SafetySupervisor,
    is_usable_limit,
)

REPO = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG = REPO / "configs" / "robot.yaml"

#: The effective clamp the shipped, digest-pinned config has produced since the
#: 2026-08-04 speed raise. R23 adds validation and MUST NOT move these numbers.
SHIPPED_VELOCITY_TRIPLE = (1.0, 0.5, 1.5)

#: Every shape of "this is not a usable limit". ``True`` is in the list on
#: purpose: YAML's ``max_vx: yes`` parses as a bool, and ``abs(v) > True``
#: silently means "1.0 m/s".
UNUSABLE_VALUES: tuple[tuple[str, Any], ...] = (
    ("nan", float("nan")),
    ("inf", float("inf")),
    ("negative_inf", float("-inf")),
    ("zero", 0),
    ("negative", -1.5),
    ("string", "fast"),
    ("bool", True),
    ("none", None),
    ("list", [1.0]),
)

VELOCITY_KEYS = ("max_vx", "max_vy", "max_vyaw")


def _shipped_config_with(overrides: dict[str, dict[str, Any]], target: Path) -> Path:
    """A full copy of the shipped config with some keys replaced.

    A copy, never the original: ``configs/robot.yaml`` is digest-pinned and any
    test that edits it in place would move two frozen digests.
    """

    data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
    for section, values in overrides.items():
        data.setdefault(section, {}).update(values)
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# 1. The digest-pinned config is unmoved
# ---------------------------------------------------------------------------


def test_shipped_robot_yaml_loads_unchanged_with_identical_limits() -> None:
    """Validation must be invisible to the frozen baseline.

    If this ever fails, R23's validation changed an effective limit on the
    shipped config and the nav baseline is no longer comparable — that is a
    card-stopping finding, not a test to update.
    """

    limits = ConfigStore(SHIPPED_CONFIG).safety_limits()
    assert (limits.max_vx, limits.max_vy, limits.max_vyaw) == SHIPPED_VELOCITY_TRIPLE
    assert limits.max_pose_duration == 10.0
    assert limits.max_abs_joint_position == 3.2


def test_shipped_robot_yaml_poses_and_wifi_cards_still_load() -> None:
    """The sibling coercions R23 also guards must stay silent on real data."""

    store = ConfigStore(SHIPPED_CONFIG)
    assert store.poses()  # skills catalog supplies these; none may be refused
    cards = store.wifi_cards()
    assert {name: card.ros_domain_id for name, card in cards.items()} == {
        "simulator": 1,
        "robot": 0,
    }


# ---------------------------------------------------------------------------
# 2. The loader refuses, by name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", VELOCITY_KEYS)
@pytest.mark.parametrize("label,value", UNUSABLE_VALUES, ids=[n for n, _ in UNUSABLE_VALUES])
def test_safety_limits_loader_refuses_an_unusable_velocity_limit(
    tmp_path: Path, key: str, label: str, value: Any
) -> None:
    config = _shipped_config_with({"motion": {key: value}}, tmp_path / "robot.yaml")
    with pytest.raises(SafetyLimitError) as caught:
        ConfigStore(config).safety_limits()
    message = str(caught.value)
    # Actionable: the file, the dotted key, and the offending value.
    assert str(config) in message
    assert f"motion.{key}" in message
    assert label in {"none", "list"} or repr(value) in message or str(value) in message


def test_safety_limits_loader_names_the_axis_not_just_the_field(tmp_path: Path) -> None:
    """``motion.max_vy`` — not ``max_vy`` — so the operator can find the line."""

    config = _shipped_config_with({"motion": {"max_vy": float("nan")}}, tmp_path / "robot.yaml")
    with pytest.raises(SafetyLimitError, match=r"motion\.max_vy must be finite"):
        ConfigStore(config).safety_limits()


def test_pose_loader_refuses_a_non_finite_joint_or_unusable_duration(tmp_path: Path) -> None:
    bad_joint = tmp_path / "joint.yaml"
    bad_joint.write_text(
        "poses:\n  sit:\n    joints: {hip: .nan}\n    duration: 1.0\n", encoding="utf-8"
    )
    with pytest.raises(SafetyLimitError, match=r"poses\.sit\.joints\.hip must be finite"):
        ConfigStore(bad_joint).poses()

    bad_duration = tmp_path / "duration.yaml"
    bad_duration.write_text(
        "poses:\n  sit:\n    joints: {hip: 0.1}\n    duration: 0\n", encoding="utf-8"
    )
    with pytest.raises(SafetyLimitError, match=r"poses\.sit\.duration must be greater than zero"):
        ConfigStore(bad_duration).poses()


def test_wifi_card_domain_id_refuses_a_non_integer(tmp_path: Path) -> None:
    config = tmp_path / "wifi.yaml"
    config.write_text(
        "wifi_cards:\n  robot:\n    interface: lo\n    ros_domain_id: 2.5\n", encoding="utf-8"
    )
    with pytest.raises(SafetyLimitError, match=r"ros_domain_id must be a whole number"):
        ConfigStore(config).wifi_cards()


# ---------------------------------------------------------------------------
# 3. The dataclass refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ("max_pose_duration", "max_abs_joint_position", "max_vx", "max_vy", "max_vyaw"),
)
@pytest.mark.parametrize("label,value", UNUSABLE_VALUES, ids=[n for n, _ in UNUSABLE_VALUES])
def test_safety_limits_dataclass_refuses_every_unusable_field(
    field: str, label: str, value: Any
) -> None:
    del label
    with pytest.raises(SafetyLimitError) as caught:
        SafetyLimits(**{field: value})
    assert field in str(caught.value)


def test_safety_limits_default_construction_still_works() -> None:
    limits = SafetyLimits()
    assert (limits.max_vx, limits.max_vy, limits.max_vyaw) == SHIPPED_VELOCITY_TRIPLE


@pytest.mark.parametrize("label,value", UNUSABLE_VALUES, ids=[n for n, _ in UNUSABLE_VALUES])
def test_is_usable_limit_rejects_everything_that_cannot_clamp(label: str, value: Any) -> None:
    del label
    assert is_usable_limit(value) is False


def test_is_usable_limit_accepts_ordinary_positive_numbers() -> None:
    assert is_usable_limit(1.0) is True
    assert is_usable_limit(1) is True
    assert is_usable_limit(1e-6) is True


# ---------------------------------------------------------------------------
# 4. Defense in depth: the comparison sites refuse an unusable limit anyway
# ---------------------------------------------------------------------------


def _bypass_validation(**overrides: Any) -> SafetyLimits:
    """Build limits that validation would have refused.

    This is how the hole reaches a live comparison in practice: ``limits`` is an
    injected attribute, so a caller can rebind or mutate it after construction.
    The comparison must not trust it.
    """

    limits = SafetyLimits()
    for name, value in overrides.items():
        object.__setattr__(limits, name, value)
    return limits


@pytest.mark.parametrize("axis", VELOCITY_KEYS)
@pytest.mark.parametrize("poison", (float("nan"), float("inf"), 0.0, -1.0))
def test_arbiter_refuses_when_a_limit_is_not_usable(axis: str, poison: float) -> None:
    arbiter = CommandArbiter(_bypass_validation(**{axis: poison}))
    result = arbiter.submit(MotionIntent(VelocityCommand(vx=1e9), source="voice"))
    assert result.accepted is False
    assert "not a usable clamp" in result.reason
    assert arbiter.current() is None


@pytest.mark.parametrize("axis", VELOCITY_KEYS)
@pytest.mark.parametrize("poison", (float("nan"), float("inf"), 0.0, -1.0))
def test_supervisor_refuses_when_a_limit_is_not_usable(axis: str, poison: float) -> None:
    supervisor = SafetySupervisor({}, limits=_bypass_validation(**{axis: poison}))
    result = supervisor.validate(ToolCall("set_velocity", {"vx": 1e9}))
    assert result.accepted is False
    assert "not a usable clamp" in result.message


def test_arbiter_refuses_a_non_finite_command_value() -> None:
    """The other side of the same comparison.

    ``MotionIntent`` already refuses non-finite commands, so this is reached
    only by a caller that constructs the intent around it — exactly the
    bypass this layer exists for.
    """

    arbiter = CommandArbiter(SafetyLimits())
    intent = MotionIntent(VelocityCommand(vx=0.1), source="voice")
    object.__setattr__(intent.command, "vx", float("nan"))
    result = arbiter.submit(intent)
    assert result.accepted is False
    assert "not a finite number" in result.reason


def test_supervisor_pose_bound_refuses_when_the_joint_limit_is_not_usable() -> None:
    """``abs(joint) > nan`` is False — the pose bound had the same hole."""

    from parcel_robot.models import Pose

    poses = {"sit": Pose(name="sit", joints={"hip": 99.0}, duration=1.0)}
    supervisor = SafetySupervisor(
        poses, limits=_bypass_validation(max_abs_joint_position=float("nan"))
    )
    result = supervisor.validate(ToolCall("run_pose", {"name": "sit"}))
    assert result.accepted is False
    assert "not a usable clamp" in result.message


def test_arbiter_and_supervisor_still_accept_and_still_refuse_normally() -> None:
    """The fail-closed rewrite must not have changed any threshold."""

    limits = SafetyLimits()
    arbiter = CommandArbiter(limits)
    assert arbiter.submit(MotionIntent(VelocityCommand(vx=0.9), source="voice")).accepted is True
    over = arbiter.submit(MotionIntent(VelocityCommand(vx=1.01), source="manual"))
    assert over.accepted is False
    assert over.reason == "vx exceeds the configured safe limit"

    supervisor = SafetySupervisor({}, limits=limits)
    assert supervisor.validate(ToolCall("set_velocity", {"vx": 0.9})).accepted is True
    refused = supervisor.validate(ToolCall("set_velocity", {"vy": 0.6}))
    assert refused.accepted is False
    assert refused.message == "vy exceeds the configured safe limit"


# ---------------------------------------------------------------------------
# 5. The operator --config path refuses at launch
# ---------------------------------------------------------------------------


def test_operator_config_with_nan_max_vx_is_refused_at_launch(tmp_path: Path) -> None:
    config = _shipped_config_with({"motion": {"max_vx": float("nan")}}, tmp_path / "robot.yaml")
    with pytest.raises(SafetyLimitError, match=r"motion\.max_vx must be finite"):
        web_panel.build_runtime(config, tmp_path / "sim.sock", use_llm=False)


def test_operator_config_that_defeated_the_control_backstop_is_refused(tmp_path: Path) -> None:
    """The composite that made the audit finding real rather than theoretical.

    Before R23 a lone ``motion.max_vx: .nan`` happened to be refused downstream
    by ``ControlLimits`` — which only fires because ``control.max_vx`` is absent
    from the shipped config and the control layer therefore falls back to the
    (poisoned) ``SafetyLimits``. Setting the equally-documented ``control.*``
    keys hands ControlLimits clean numbers and the NaN sails into the arbiter
    and the SafetySupervisor. This case is the one that must stay refused.
    """

    config = _shipped_config_with(
        {
            "motion": {"max_vx": float("nan")},
            "control": {"max_vx": 1.0, "max_vy": 0.5, "max_vyaw": 1.5},
        },
        tmp_path / "robot.yaml",
    )
    with pytest.raises(SafetyLimitError) as caught:
        web_panel.build_runtime(config, tmp_path / "sim.sock", use_llm=False)
    # Refused by the SAFETY loader, not by the control-layer accident.
    assert "motion.max_vx" in str(caught.value)


def test_shipped_config_still_launches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the launch proof: a good config is not refused.

    CARD R27 — THIS TEST WAS THE POLLUTION VECTOR, and it shipped in the repo.

    It builds a runtime from ``configs/robot.yaml``, whose ``memory.path`` is
    the relative string ``parcel_memory.sqlite3``. pytest runs with the repo
    root as CWD, so until R27 that string named **the owner's real conversation
    memory** and this test opened it for writing on every commit-tier gate run.
    A ``sqlite3.connect`` probe over the whole 7,686-test commit tier found
    exactly one test doing so, and it was this one.

    ``PARCEL_MEMORY_PATH`` is the documented escape hatch (see
    ``src/parcel_robot/memory_path.py``); pointing it at ``tmp_path`` is what
    every test that needs a real runtime should now do. Without it the
    constructor raises ``MemoryPathRefused`` rather than writing — which is the
    point of the card, and which
    ``tests/test_owner_store_isolation.py`` asserts directly.
    """

    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    runtime = web_panel.build_runtime(SHIPPED_CONFIG, tmp_path / "sim.sock", use_llm=False)
    assert runtime.arbiter.limits.max_vx == SHIPPED_VELOCITY_TRIPLE[0]
    assert runtime.agent.safety.limits.max_vx == SHIPPED_VELOCITY_TRIPLE[0]


# ---------------------------------------------------------------------------
# 6. The doctrine test
# ---------------------------------------------------------------------------


def _load_velocity_limits(value: Any, tmp_path: Path) -> None:
    config = _shipped_config_with({"motion": {"max_vx": value}}, tmp_path / "doctrine.yaml")
    ConfigStore(config).safety_limits()


#: Every loader in this repo that DOCUMENTS itself fail-closed, paired with one
#: numeric key it owns. A new numeric key added to any of these without
#: validation reddens the row it belongs to.
#:
#: (name, callable taking one poisoned value, expected exception)
FAIL_CLOSED_LOADERS: tuple[tuple[str, Callable[[Any, Path], Any], type[Exception]], ...] = (
    (
        "robot.yaml motion velocity limits (config.py safety_limits)",
        _load_velocity_limits,
        SafetyLimitError,
    ),
    (
        "robot.yaml safety.time_to_collision (navigation/dynamic_layer.py)",
        lambda value, _: TimeToCollisionConfig.from_mapping({"brake_s": value}),
        Exception,
    ),
    (
        "robot.yaml motion.shaping (core/motion_shaping.py)",
        lambda value, _: MotionShapingConfig.from_mapping({"linear_max_accel": value}),
        Exception,
    ),
    (
        "robot.yaml owner_follow.prediction (navigation/follow.py)",
        lambda value, _: FollowPredictionConfig.from_mapping({"lead_s": value}),
        Exception,
    ),
    (
        "robot.yaml owner_search (navigation/search_owner.py)",
        lambda value, _: SearchOwnerConfig.from_mapping({"max_search_s": value}),
        Exception,
    ),
    (
        "robot.yaml duplex (duplex/config.py)",
        lambda value, _: DuplexConfig.from_mapping({"frame_hz": value}),
        Exception,
    ),
    (
        "realtime.yaml (realtime/config.py)",
        lambda value, _: realtime_config_from_mapping(
            {"stall_timeout_s": value}, source="doctrine"
        ),
        RealtimeConfigError,
    ),
)

#: The doctrine's own poison set — the floor every documented fail-closed
#: loader clears TODAY. One shape is deliberately absent, because a real loader
#: still accepts it, and it is pinned by its own registered-gap test below so
#: the hole stays visible in the suite instead of being quietly excluded:
#:
#:   * ``True`` — accepted by 8 loaders that coerce it to 1.0
#:     (``test_documented_loaders_still_coerce_true_to_one_registered_gap``)
#:
#: It is out-of-OWNS for card R23 and registered as an owner-gated finding in
#: scrum/20260821/task_2/R23_STATUS.md.
#:
#: ``+inf`` used to be the second entry here, accepted by
#: ``realtime/config.py::_positive``. Card R25 owns that file's validation and
#: closed it (``scrum/20260821/task_4/R25_STATUS.md``): the registered-gap test
#: is gone and the skip in
#: ``test_documented_fail_closed_loaders_that_R23_owns_also_refuse_infinity``
#: is gone with it, so ``+inf`` is now asserted against every loader in the
#: table rather than recorded as a hole.
DOCTRINE_POISONS: tuple[tuple[str, Any], ...] = (
    ("nan", float("nan")),
    ("zero", 0),
    ("negative", -1),
    ("string", "soon"),
)


@pytest.mark.parametrize("name,loader,expected", FAIL_CLOSED_LOADERS, ids=[
    row[0].split(" (")[0] for row in FAIL_CLOSED_LOADERS
])
@pytest.mark.parametrize("label,value", DOCTRINE_POISONS, ids=[n for n, _ in DOCTRINE_POISONS])
def test_every_documented_fail_closed_loader_refuses_a_malformed_number(
    tmp_path: Path,
    name: str,
    loader: Callable[[Any, Path], Any],
    expected: type[Exception],
    label: str,
    value: Any,
) -> None:
    """The doctrine, in one assertion per (loader, malformed value).

    ``realtime/config.py`` states it: "Unknown keys raise, wrong types raise,
    and negative budgets raise." This test is what makes that a property of the
    repository rather than of one file.
    """

    del label
    with pytest.raises(expected):
        loader(value, tmp_path)
    assert name  # keeps the loader name in the failure output


@pytest.mark.parametrize("name,loader,expected", FAIL_CLOSED_LOADERS, ids=[
    row[0].split(" (")[0] for row in FAIL_CLOSED_LOADERS
])
def test_documented_fail_closed_loaders_that_R23_owns_also_refuse_infinity(
    tmp_path: Path,
    name: str,
    loader: Callable[[Any, Path], Any],
    expected: type[Exception],
) -> None:
    """``+inf`` is a limit that permits every finite value — it must refuse too.

    The ``realtime.yaml`` row used to be skipped here: R23 measured that
    ``realtime/config.py::_positive`` accepted ``+inf`` and could not fix it,
    because that package was outside its OWNS list. Card R25 owns it and fixed
    it, so the skip is gone and this parametrization now covers every loader in
    :data:`FAIL_CLOSED_LOADERS` with no exceptions. ``name`` is kept in the
    signature so a failure names the loader.
    """

    assert name
    with pytest.raises(expected):
        loader(float("inf"), tmp_path)


def test_realtime_config_refuses_infinity_on_every_positive_key() -> None:
    """Card R25, closing R23's registered gap §7.2 — the direction it matters in.

    ``_positive`` tested ``not number > 0.0``, which refuses NaN by accident of
    IEEE comparison (``nan > 0`` is False) and ACCEPTED ``float("inf")`` by the
    same accident. In this file ``+inf`` meant an infinite stall timeout, an
    unbounded session, a microphone that never idle-closes, and — the one that
    made it R25's problem — an **unlimited monthly budget**, i.e. a ceiling that
    a config typo could remove entirely on the very card that made the ceiling
    real. Each key is asserted separately: a fix applied to one call site and
    not the others is the failure this parametrization exists to catch.
    """

    for key in ("stall_timeout_s", "session_max_s", "idle_close_after_s", "monthly_budget_usd"):
        for poison in (float("inf"), float("-inf")):
            with pytest.raises(RealtimeConfigError) as caught:
                realtime_config_from_mapping({key: poison}, source="r25")
            assert key in str(caught.value)
            assert "finite" in str(caught.value)
    # And the finite value still loads, so the fix is a refusal and not a wall.
    assert realtime_config_from_mapping(
        {"monthly_budget_usd": 40.0}, source="r25"
    ).monthly_budget_usd == 40.0
    assert not math.isinf(
        realtime_config_from_mapping({"session_max_s": 1800}, source="r25").session_max_s
    )


#: Loaders that turn YAML's ``key: yes`` (a bool) into the number 1.0. Found by
#: R23's sweep; NOT fixed by R23 because every one of these files is outside the
#: card's OWNS list. Each entry is (dotted key, callable).
TRUE_COERCING_LOADERS: tuple[tuple[str, Callable[[Any], Any]], ...] = (
    ("safety.time_to_collision.brake_s", lambda v: TimeToCollisionConfig.from_mapping({"brake_s": v})),
    ("motion.shaping.linear_max_accel", lambda v: MotionShapingConfig.from_mapping({"linear_max_accel": v})),
    ("owner_follow.prediction.lead_s", lambda v: FollowPredictionConfig.from_mapping({"lead_s": v})),
    ("owner_search.sensor_radius_m", lambda v: SearchOwnerConfig.from_mapping({"sensor_radius_m": v})),
    ("duplex.frame_hz", lambda v: DuplexConfig.from_mapping({"frame_hz": v})),
)


@pytest.mark.parametrize("key,loader", TRUE_COERCING_LOADERS, ids=[k for k, _ in TRUE_COERCING_LOADERS])
def test_documented_loaders_still_coerce_true_to_one_registered_gap(
    key: str, loader: Callable[[Any], Any]
) -> None:
    """A KNOWN GAP, pinned so it stays visible — not an endorsement.

    ``float(True)`` is ``1.0``, so YAML's ``brake_s: yes`` reads as one second
    rather than refusing. ``realtime/config.py`` and R23's own loader both
    reject bools explicitly (``isinstance(value, bool)`` first); these five do
    not. Every file listed here is outside card R23's OWNS list, so the gap is
    recorded rather than fixed.

    The fix, for whoever owns the follow-up, is the same one line each loader's
    bool-valued keys already use::

        if isinstance(value, bool): raise TypeError(...)

    When a row here is fixed, delete it — this test will redden and say so.
    """

    loader(True)  # must NOT raise today; deleting the row is how it gets fixed


def test_r23_owned_loader_rejects_true_unlike_the_registered_gap() -> None:
    """The contrast that makes the gap above a gap and not a convention."""

    with pytest.raises(SafetyLimitError, match="must be a number"):
        SafetyLimits(max_vx=True)
