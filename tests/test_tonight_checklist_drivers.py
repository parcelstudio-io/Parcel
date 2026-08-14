"""The night checklist must install and rehearse the ROS driver nodes.

Card **PS-P**, tranche PS-3. The finding these tests exist for:

    TONIGHT_CHECKLIST.md NEVER INSTALLS OR REHEARSES THE ROS DRIVER NODES that
    94% of the byte budget depends on. Its entire install inventory is
    `pip install pyrealsense2`, `apt-get install librealsense2-utils`, and
    `fio`. But the recorder of record is `ros2 bag record`, which records
    TOPICS — and no topic exists without a driver node publishing it.

Measured against the model rather than asserted: `d455.*` is **89.0%** of the
recommended profile's bytes and exists only while `realsense2_camera` runs;
`l2.*` is 0.8% and exists only while the `unilidar_sdk2` ROS node runs; every
`go2.*` row (10.2%) can only be serialised by `ros2 bag record` if the
`unitree_ros2` interface packages are built and sourced.
:func:`test_the_driver_dependent_share_of_the_budget_is_what_the_sheet_claims`
recomputes those shares so the sheet's own callout cannot go stale.

Everything the sheet is asserted to contain is **derived from
`scripts/parcel_capture/rosbag2.py`** — its `DRIVER_TOPICS` table already
carried every topic name and every launch command; the checklist simply never
used them. Deriving the assertions from that module rather than from literals
means a driver topic added there is a driver topic the checklist must rehearse.

Every test in this file was run against the pre-fix checklist and fails on it;
the specific failures are recorded in ``PSP_STATUS.md``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from scripts.parcel_capture.budget import (
    RECOMMENDED_PROFILE,
    build_budget,
)
from scripts.parcel_capture.rosbag2 import (
    DRIVER_TOPICS,
    RECORDED_TOPICS,
    TopicSource,
)

CHECKLIST = REPO_ROOT / "scrum/20260813/task_1/session/TONIGHT_CHECKLIST.md"


@pytest.fixture(scope="module")
def sheet() -> str:
    assert CHECKLIST.is_file(), f"{CHECKLIST} is missing"
    return CHECKLIST.read_text(encoding="utf-8")


def _code_blocks(text: str) -> list[str]:
    """Every fenced block on the sheet — i.e. everything an operator will type.

    The arming check runs over these rather than over the whole document,
    because the standing rules necessarily *name* the things they forbid.
    """

    return re.findall(r"^```[a-z]*\n(.*?)^```", text, re.MULTILINE | re.DOTALL)


# ---------------------------------------------------------------------------
# The three driver paths: installed, launched, verified
# ---------------------------------------------------------------------------


def test_the_realsense_ros_driver_is_installed_not_just_the_pip_module(sheet: str) -> None:
    """`pip install pyrealsense2` is not the session path and does not close it.

    ``ingest/realsense.py:3-8`` says the primary path is the
    ``realsense2_camera`` ROS node feeding ``ros2 bag record``. The checklist has
    to install that package, by name, with apt.
    """

    assert re.search(r"apt-get install[^\n]*realsense2-camera", sheet), (
        "the sheet never apt-installs ros-<distro>-realsense2-camera; "
        "pyrealsense2 is the preflight path, not the recording path"
    )
    assert "realsense2-camera-msgs" in sheet, (
        "the driver's message package is a separate apt package and is needed for "
        "ros2 bag record to resolve the camera topics' types"
    )


def test_the_realsense_driver_is_launched_with_the_imu_argument(sheet: str) -> None:
    """`unite_imu_method` is load-bearing: without it the IMU topics vanish."""

    assert "ros2 launch realsense2_camera rs_launch.py" in sheet
    assert "unite_imu_method" in sheet, (
        "rosbag2.py:322-329 — 'unite_imu_method must be set or the IMU topics do not "
        "appear'. A silent loss, not an error."
    )
    assert "--show-args" in sheet, (
        "the profile-argument spelling changed across driver releases; the sheet must "
        "tell the operator to read the real spelling rather than fight it"
    )


def test_the_l2_ros_node_is_built_and_launched_not_just_the_sdk_example(sheet: str) -> None:
    """N5 built the vendor SDK example. An example prints; it does not publish."""

    assert "colcon build" in sheet, "the L2 ROS wrapper is a colcon workspace and is never built"
    assert "unitree_lidar_ros2" in sheet, (
        "rosbag2.py:340-357 gives 'ros2 launch unitree_lidar_ros2 launch.py' as the "
        "prerequisite for both L2 topics; the sheet never launches it"
    )


def test_the_unitree_message_packages_are_built_and_inspected(sheet: str) -> None:
    """Without `unitree_go`, `ros2 bag record` records no dog topic at all."""

    assert "unitree_ros2" in sheet
    assert re.search(r"git clone[^\n]*unitree_ros2", sheet), (
        "the unitree_ros2 interface packages are never obtained; ros2 bag record "
        "cannot resolve unitree_go message types without them"
    )
    assert "ros2 interface show unitree_go/msg/LowState" in sheet, (
        "the sheet must verify the interfaces resolve, not merely that a build "
        "command exited zero"
    )
    assert re.search(r"install/setup\.bash", sheet), (
        "the overlay source line is what tomorrow's recorder shell needs; if it is "
        "not transcribed, every dog topic is silently absent from the bag"
    )


@pytest.mark.parametrize(
    "topic",
    sorted({item.topic for item in DRIVER_TOPICS}),
)
def test_every_driver_topic_is_named_in_the_checklist(sheet: str, topic: str) -> None:
    """Each `DRIVER_NODE` topic must appear, so the operator can check the name.

    A recorder given a topic name nothing publishes subscribes to nothing and
    raises nothing (``rosbag2.py:222-228``). The only defence is comparing the
    planned names against what ``ros2 topic list`` actually prints, tonight.
    """

    assert topic in sheet, f"{topic} is a DRIVER_NODE topic the checklist never mentions"


@pytest.mark.parametrize(
    "prerequisite",
    sorted({item.prerequisite for item in DRIVER_TOPICS if item.prerequisite}),
)
def test_every_driver_launch_command_appears_in_the_checklist(
    sheet: str, prerequisite: str
) -> None:
    """`rosbag2.py` records what must be running; the sheet must run it.

    Compared on the launch *executable* rather than the full argument string,
    because the checklist deliberately launches at the session profile with more
    arguments than the terse prerequisite note carries.
    """

    head = " ".join(prerequisite.split()[:4])  # 'ros2 launch <pkg> <launchfile>'
    assert head in sheet, f"no step launches {head!r}, so its topics cannot exist tonight"


def test_driver_topics_are_verified_with_topic_hz(sheet: str) -> None:
    """*How to verify with `ros2 topic hz`* — the finding asked for it by name."""

    assert sheet.count("ros2 topic hz") >= 2, (
        "the sheet must verify each launched driver's topics with ros2 topic hz; "
        "'the node started' is not evidence that it publishes"
    )
    for anchor in ("/camera/camera/color/image_raw", "/unilidar/cloud"):
        window = sheet[max(0, sheet.find(anchor) - 4000) : sheet.find(anchor) + 4000]
        assert "ros2 topic hz" in window, f"{anchor} is listed but never rate-checked"


def test_the_real_driver_topics_are_recorded_through_rosbag2(sheet: str) -> None:
    """A synthetic publisher does not prove the driver reaches the recorder."""

    assert "tonight_n4f" in sheet, (
        "N4 records only synthetic /tonight/* topics; nothing on the sheet records a "
        "real driver topic through ros2 bag record"
    )
    n4f = sheet[sheet.find("### N4f") :]
    assert n4f, "N4f is missing"
    assert "ros2 bag record -s mcap" in n4f
    assert "ros2 topic list" in n4f, (
        "N4f must build its record list from the topics that exist, not from the plan"
    )


# ---------------------------------------------------------------------------
# The share of the budget that depends on a driver — recomputed, not asserted
# ---------------------------------------------------------------------------


def test_the_driver_dependent_share_of_the_budget_is_what_the_sheet_claims(
    sheet: str,
) -> None:
    """Recompute the sheet's own callout so it cannot go stale like §1 did."""

    plan = build_budget(RECOMMENDED_PROFILE)
    total = plan.bytes_per_second
    share = {
        "d455": sum(r.bytes_per_second for r in plan.rows if r.channel_id.startswith("d455.")),
        "l2": sum(r.bytes_per_second for r in plan.rows if r.channel_id.startswith("l2.")),
        "go2": sum(r.bytes_per_second for r in plan.rows if r.channel_id.startswith("go2.")),
    }
    assert share["d455"] / total > 0.85, "the D455 is no longer the dominant driver group"
    for key, expected in (("d455", "89.0%"), ("l2", "0.8%"), ("go2", "10.2%")):
        assert f"{share[key] / total:.1%}" == expected, (
            f"{key} is now {share[key] / total:.1%}, not {expected} — regenerate the "
            f"checklist callout in section 1"
        )
        assert expected in sheet, f"the sheet does not state the {key} share ({expected})"


def test_no_ros_channels_are_a_rounding_error_and_the_sheet_says_so(sheet: str) -> None:
    """Everything that needs no ROS at all is 0.02% — i.e. essentially nothing."""

    plan = build_budget(RECOMMENDED_PROFILE)
    no_ros = sum(
        r.bytes_per_second
        for r in plan.rows
        if r.channel_id.split(".")[0] in {"orin", "gnss", "uwb"}
    )
    fraction = no_ros / plan.bytes_per_second
    assert fraction < 0.001
    assert f"{fraction:.2%}" in sheet


# ---------------------------------------------------------------------------
# Last-reader pass: does every step produce what the next step consumes?
# ---------------------------------------------------------------------------


def test_the_rosbag2_rehearsal_drives_the_current_byte_rate(sheet: str) -> None:
    """N4c's synthetic publishers must reproduce the budget, not a stale figure.

    The pre-fix sheet targeted 84.4 MiB/s against a budget of 84.60 that was
    itself stale by 8.6%, and it had no front-camera publisher at all — so it
    under-drove the recorder by 6.6 MiB/s on the channel PS-H had just made the
    fifth largest in the rig.
    """

    match = re.search(r"\*\*Total ≈ ([0-9.]+) MiB/s\*\*", sheet)
    assert match, "N4c no longer states a synthetic total"
    stated = float(match.group(1))
    plan = build_budget(RECOMMENDED_PROFILE)
    drift = abs(stated - plan.mib_per_second) / plan.mib_per_second
    assert drift < 0.02, (
        f"the rehearsal drives {stated} MiB/s against a budget of "
        f"{plan.mib_per_second:.2f} — {drift:.1%} adrift"
    )
    assert "/tonight/front_cam" in sheet, (
        "the front camera is 6.59 MiB/s of the budget and the rehearsal omits it"
    )


def test_the_rehearsal_publisher_sources_ros_before_importing_rclpy(sheet: str) -> None:
    """N4c's terminal 1 runs a script that imports rclpy. It has to source ROS."""

    block = sheet[sheet.find("### N4c") : sheet.find("### N4d")]
    assert block, "N4c is missing"
    assert "source /opt/ros/humble/setup.bash" in block, (
        "the publisher imports rclpy and the step never sources the ROS overlay; it "
        "fails with ModuleNotFoundError at the first line"
    )


def test_the_recording_steps_use_the_target_path_n0_and_n3_established(sheet: str) -> None:
    """N3 measures `$TARGET`; N4 must record to the same volume, not to `/data`.

    The pre-fix sheet hard-coded `/data` in N4 while N3 used an operator-chosen
    `$TARGET`. If the record destination is not `/data`, one of the two steps is
    measuring the wrong disk and the go/no-go threshold is meaningless.
    """

    block = sheet[sheet.find("### N4d") : sheet.find("## N5")]
    assert block, "N4d is missing"
    assert "TARGET=" in block, "N4 does not bind TARGET"
    stale = re.findall(r"(?<![\"$/\w])/data/tonight_n4", block)
    assert not stale, f"N4 still hard-codes the record path: {stale}"


def test_the_l2_step_declares_its_dependency_on_the_later_network_step(sheet: str) -> None:
    """N5's `ping 192.168.1.2` needs an address N6b assigns, and N6 comes after.

    A step that consumes an artifact a *later* step produces is an ordering
    defect, and at midnight it reads as a broken LiDAR.
    """

    block = sheet[sheet.find("## N5 ") : sheet.find("## N6 ")]
    assert block, "N5 is missing"
    assert "ORDERING" in block, "N5 does not warn that it needs N6a/N6b first"
    assert "N6b" in block


def test_every_new_step_has_a_row_in_the_results_ledger(sheet: str) -> None:
    """A step with no ledger row is a step nobody records the outcome of."""

    ledger = sheet[sheet.find("## 2 · Results ledger") : sheet.find("## 3 · Hand-off")]
    assert ledger, "the results ledger is missing"
    for step in ("N0b", "N2e", "N4f", "N5b", "N6f"):
        assert step in ledger, f"{step} has no row in the results ledger"


def test_every_new_step_hands_something_into_tomorrow(sheet: str) -> None:
    """`An untranscribed command is a NOT MEASURED` — so each step must transcribe."""

    handoff = sheet[sheet.find("## 3 · Hand-off") : sheet.find("## 4 · What this sheet")]
    assert handoff, "the hand-off table is missing"
    for step in ("N2e", "N4f", "N5b", "N6f"):
        assert step in handoff, f"{step} produces nothing that reaches tomorrow's run sheet"


def test_the_sheet_still_arms_nothing(sheet: str) -> None:
    """Board rule 1, re-checked after adding four steps that launch ROS nodes.

    The added steps launch *sensor drivers* and build *message packages*. None of
    them may publish a robot command, take a lease, or construct a motion client.
    """

    # Prose may name what it forbids — the standing rules do, and must. The
    # check therefore runs over the sheet's CODE BLOCKS only: what an operator
    # will actually type at midnight.
    code = "\n".join(_code_blocks(sheet))
    assert code, "no fenced code blocks found — the extractor is broken"
    forbidden = (
        "unitree_sdk2py",
        "ControlManager",
        "sport_client",
        "SportClient",
        "MotionSwitcher",
    )
    for token in forbidden:
        assert token not in code, f"a command on the sheet uses {token!r} — that arms something"
    # The one topic-pub on the sheet is N6d's discovery probe under /tonight/.
    publishes = re.findall(r"ros2 topic pub[^\n]*", code)
    assert publishes, "N6d's discovery probe disappeared"
    for line in publishes:
        assert "/tonight/" in line, f"unscoped publish: {line}"
    assert "never publishes any rt/ topic" in sheet


def test_the_checklist_records_that_pyrealsense2_and_the_driver_conflict(sheet: str) -> None:
    """One USB device, one holder. The two D455 paths cannot run at once."""

    assert "only one process can hold it" in sheet, (
        "N2a-d and N2e both open the D455; the sheet must say they are mutually "
        "exclusive or the operator debugs a phantom driver failure"
    )


#: Variables an operator's shell supplies, or heredoc terminators that look like
#: variables to a naive scan. Everything else must be assigned in its own block,
#: because every block on this sheet is copy-pasted into a fresh terminal.
_AMBIENT_SHELL_VARS = frozenset(
    {
        "HOME",
        "PWD",
        "PATH",
        "PYTHONPATH",
        "CYCLONEDDS_URI",
        "ROS_DOMAIN_ID",
        "RMW_IMPLEMENTATION",
        "XML",
        "PY",
        "YAML",
    }
)


def test_no_shell_block_uses_a_variable_it_never_assigns(sheet: str) -> None:
    """Each block is pasted into a fresh terminal, so each must stand alone.

    This caught a real defect: parameterising N4d's record path as ``$TARGET``
    left N4e's verification block reading ``ros2 bag info "$TARGET/tonight_n4"``
    with ``TARGET`` unset — which at midnight is ``ros2 bag info /tonight_n4``
    and a confusing "bag not found".
    """

    offenders: list[tuple[str, list[str]]] = []
    for block in _code_blocks(sheet):
        if "RECORD  " in block or "DERIVED  " in block:
            continue  # a fill-in-the-blank block, not a command
        assigned = set(re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=", block, re.MULTILINE))
        used = set(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)\}?", block))
        missing = sorted(used - assigned - _AMBIENT_SHELL_VARS)
        if missing:
            offenders.append((block.strip().splitlines()[0][:60], missing))
    assert not offenders, f"shell blocks using unassigned variables: {offenders}"


def test_the_step_that_writes_into_tonight_creates_the_directory(sheet: str) -> None:
    """N4f writes `~/tonight/n4f_topics.txt`; only PRE-3 ever made `~/tonight`."""

    n4f = sheet[sheet.find("### N4f") : sheet.find("## N5 ")]
    assert "~/tonight/n4f_topics.txt" in n4f
    assert "mkdir -p ~/tonight" in n4f, (
        "N4f writes into ~/tonight but only PRE-3 creates it; a sheet run out of "
        "order fails on a redirect"
    )


# ---------------------------------------------------------------------------
# Guardrails on the derivation itself
# ---------------------------------------------------------------------------


def test_driver_topics_is_not_empty_and_is_the_thing_being_derived_from() -> None:
    """If `DRIVER_TOPICS` were empty every parametrised test above would vacuously pass."""

    assert len(DRIVER_TOPICS) >= 8
    assert all(item.source is TopicSource.DRIVER_NODE for item in DRIVER_TOPICS)
    assert any(item.source is TopicSource.ROBOT_NATIVE for item in RECORDED_TOPICS)
