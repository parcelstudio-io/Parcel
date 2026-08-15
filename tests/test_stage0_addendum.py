"""The per-distro Stage-0 sheets are generated, and this is their pin.

Card **S-2** (``scrum/20260814/task_1/REVISED_BOARD.md``): the four missing
operator command rows T7-T10, rendered as **run-specific, distro-parameterised**
sheets — ``STAGE0_ADDENDUM_HUMBLE.md`` and ``STAGE0_ADDENDUM_JAZZY.md``. Exactly
one becomes operative when H-1 reports the Orin's observed distro; the other is
void.

Working agreement 7 — *one source of recorder argv truth* — is what these tests
enforce. The precedent is ``tests/test_bandwidth_budget_doc.py``: a frozen
digest pins bytes to a constant, and this pins bytes to **what the code
computes**, which is the property that actually failed in the historical
sheets (they hard-code ``--disable-keyboard-controls``, a flag Humble's
recorder does not declare — argparse exit 2, zero bytes recorded).

Six layers, each catching a different way of going wrong:

1. **byte identity** — the committed sheet equals :func:`render_addendum`;
2. **extraction** — the argv is parsed back **out** of the committed markdown
   and compared to :func:`rosbag2.record_command`, so a hand-edited command
   line is caught even if somebody also re-ran the generator;
3. **the distro gate** — injecting a Humble-incompatible flag into a Humble row
   is refused at construction, before a byte of Markdown is rendered;
4. **fail closed** — an unknown distro string is a refusal, never a default;
5. **anti-drift** — the RealSense launch arguments are derived from the
   recording plan, proved by mutating the plan and watching the launch line
   follow it;
6. **cross-check** — every S-1 gate the sheet names by symbol is asserted to
   exist in S-1's live modules.

Regenerate with::

    .parcel/bin/python -m scripts.parcel_capture.stage0_addendum --emit-all-distros
"""

from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from scripts.parcel_capture import rosbag2 as rb
from scripts.parcel_capture import stage0_addendum as s0

DISTROS = (rb.RosDistro.HUMBLE, rb.RosDistro.JAZZY)

#: Flags that exist only on Jazzy's recorder verb. PS-M F3 measured all three
#: against ``ros2/rosbag2``'s own ``record.py``. Literals on purpose: deriving
#: them from ``rosbag2._DISTRO_ONLY_FLAGS`` would make this test agree with
#: itself about the very thing it exists to check.
JAZZY_ONLY_FLAGS = ("--topics", "--disable-keyboard-controls", "--node-name")


def _plan(distro: rb.RosDistro) -> rb.Rosbag2Plan:
    return rb.plan_for_session(
        s0.S2_OUTPUT_DIR,
        storage_config_path=s0.S2_STORAGE_CONFIG_PATH,
        distro=distro,
    )


# ---------------------------------------------------------------------------
# Layer 1: the committed sheets are what the code renders
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("distro", DISTROS)
def test_committed_sheet_is_byte_identical_to_the_generator(distro: rb.RosDistro) -> None:
    path = s0.document_path(distro)
    assert path.exists(), (
        f"{path} is missing; emit it with .parcel/bin/python -m "
        f"scripts.parcel_capture.stage0_addendum --emit-all-distros"
    )
    assert path.read_text(encoding="utf-8") == s0.render_addendum(distro), (
        f"{path.name} diverges from render_addendum({distro.value!r}); regenerate — "
        f"never hand-edit an operator command"
    )


@pytest.mark.parametrize("distro", DISTROS)
def test_a_hand_edit_to_the_committed_sheet_reddens_the_pin(distro: rb.RosDistro) -> None:
    """Seeded failure (b): the pin must actually be comparing something.

    The edit chosen is the plausible one — an operator who "knows" the cache
    size should be the recorder's default and edits it in Markdown rather than
    in the plan.
    """

    committed = s0.document_path(distro).read_text(encoding="utf-8")
    assert "--max-cache-size 8388608" in committed
    hand_edited = committed.replace(
        "--max-cache-size 8388608", "--max-cache-size 104857600", 1
    )
    assert hand_edited != committed
    assert hand_edited != s0.render_addendum(distro)


def test_the_renderer_is_byte_stable_across_calls() -> None:
    """No timestamps, no host lookups: two calls must be identical bytes."""

    for distro in DISTROS:
        assert s0.render_addendum(distro) == s0.render_addendum(distro)


# ---------------------------------------------------------------------------
# Layer 2: the argv parsed back OUT of the committed markdown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("distro", DISTROS)
def test_the_committed_argv_equals_record_command(distro: rb.RosDistro) -> None:
    text = s0.document_path(distro).read_text(encoding="utf-8")
    extracted = s0.extract_argv_from_addendum(text, distro)
    assert extracted == rb.record_command(_plan(distro))


@pytest.mark.parametrize("distro", DISTROS)
def test_the_committed_storage_config_equals_storage_config_yaml(
    distro: rb.RosDistro,
) -> None:
    text = s0.document_path(distro).read_text(encoding="utf-8")
    assert s0.extract_storage_config_from_addendum(text) == rb.storage_config_yaml()


def test_a_hand_invented_argv_fails_the_extraction_check() -> None:
    """The layer-2 oracle must reject a forged command line."""

    text = s0.render_addendum(rb.RosDistro.HUMBLE)
    real = " ".join(rb.record_command(_plan(rb.RosDistro.HUMBLE)))
    forged = text.replace(real, "ros2 bag record -a --disable-keyboard-controls", 1)
    extracted = s0.extract_argv_from_addendum(forged, rb.RosDistro.HUMBLE)
    assert extracted != rb.record_command(_plan(rb.RosDistro.HUMBLE))
    assert "-a" in extracted


def test_the_humble_sheet_carries_no_jazzy_only_flag() -> None:
    argv = s0.extract_argv_from_addendum(
        s0.document_path(rb.RosDistro.HUMBLE).read_text(encoding="utf-8"),
        rb.RosDistro.HUMBLE,
    )
    for flag in JAZZY_ONLY_FLAGS:
        assert flag not in argv, f"{flag} on a Humble command line is exit 2, zero bytes"


def test_the_jazzy_sheet_carries_the_jazzy_only_flags() -> None:
    """The negative control: the two sheets must not be the same document."""

    argv = s0.extract_argv_from_addendum(
        s0.document_path(rb.RosDistro.JAZZY).read_text(encoding="utf-8"),
        rb.RosDistro.JAZZY,
    )
    for flag in JAZZY_ONLY_FLAGS:
        assert flag in argv


# ---------------------------------------------------------------------------
# Layer 3: the distro gate refuses before render
# ---------------------------------------------------------------------------


def test_a_humble_incompatible_flag_is_refused_before_any_render() -> None:
    """Seeded failure (a). The injected flag never reaches Markdown."""

    with pytest.raises(s0.AddendumRefusedError) as caught:
        s0.check_recorder_line(
            "ros2 bag record --storage mcap --disable-keyboard-controls /lowstate",
            rb.RosDistro.HUMBLE,
            where="T10.6",
        )
    message = str(caught.value)
    assert "--disable-keyboard-controls" in message
    assert "ZERO bytes" in message


def test_the_same_flag_is_accepted_for_jazzy() -> None:
    """The gate must be distro-aware, not a blanket denylist."""

    flags = s0.check_recorder_line(
        "ros2 bag record --storage mcap --disable-keyboard-controls /lowstate",
        rb.RosDistro.JAZZY,
    )
    assert "--disable-keyboard-controls" in flags


def test_injecting_the_flag_into_a_humble_ROW_refuses_at_construction() -> None:
    """The gate is on the Addendum, not only on a helper nobody has to call."""

    good = s0.build_addendum(rb.RosDistro.HUMBLE)
    t10 = good.sections[3]
    argv_row = next(row for row in t10.rows if row.argv_markers)
    poisoned_row = replace(
        argv_row,
        command=(argv_row.command[0] + " --disable-keyboard-controls",),
    )
    poisoned_section = replace(
        t10, rows=tuple(poisoned_row if row is argv_row else row for row in t10.rows)
    )
    with pytest.raises(s0.AddendumRefusedError) as caught:
        replace(
            good,
            sections=tuple(
                poisoned_section if sec is t10 else sec for sec in good.sections
            ),
        )
    assert "--disable-keyboard-controls" in str(caught.value)


def test_the_shipped_addendum_is_constructible_for_both_distros() -> None:
    """The gate above must not be passing because construction always fails."""

    for distro in DISTROS:
        addendum = s0.build_addendum(distro)
        assert tuple(section.key for section in addendum.sections) == s0.SECTION_KEYS


# ---------------------------------------------------------------------------
# Layer 4: fail closed on the distro
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["foxy", "iron", "rolling", "", "  ", "HUMBLE2"])
def test_an_unknown_distro_string_is_refused_never_defaulted(bad: str) -> None:
    """Seeded failure (c)."""

    with pytest.raises(s0.AddendumRefusedError) as caught:
        s0.parse_distro(bad)
    assert "VOID" in str(caught.value)


def test_a_non_string_distro_is_refused() -> None:
    with pytest.raises(s0.AddendumRefusedError):
        s0.parse_distro(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("good", ["humble", "JAZZY", " humble ", "Jazzy"])
def test_a_known_distro_string_parses(good: str) -> None:
    assert s0.parse_distro(good) in DISTROS


def test_the_cli_refuses_an_unknown_distro_with_an_actionable_message(capsys) -> None:
    assert s0.main(["--distro", "foxy", "--out", "-"]) == 2
    assert "refused:" in capsys.readouterr().err


def test_the_cli_writes_the_sheet_it_is_asked_for(tmp_path: Path) -> None:
    target = tmp_path / "sheet.md"
    assert s0.main(["--distro", "jazzy", "--out", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == s0.render_addendum(rb.RosDistro.JAZZY)


# ---------------------------------------------------------------------------
# Layer 5: anti-drift — the launch line follows the recording plan
# ---------------------------------------------------------------------------


def test_the_launch_arguments_match_the_plans_own_d455_rows() -> None:
    args = s0.realsense_launch_arguments()
    for row in s0.d455_topics():
        assert row.channel_id is not None
        enable = s0._D455_LAUNCH_ENABLE[row.channel_id]
        assert f"{enable}:=true" in args, f"{row.topic} on the plan but never launched"
    profile = f"{s0.RECOMMENDED_PROFILE.width}x{s0.RECOMMENDED_PROFILE.height}x{s0.RECOMMENDED_PROFILE.fps}"
    assert f"rgb_camera.color_profile:={profile}" in args
    assert "unite_imu_method:=linear_interpolation" in args


def test_dropping_a_stream_from_the_plan_drops_it_from_the_launch_line() -> None:
    """The anti-drift claim, executed rather than asserted in a comment."""

    trimmed = tuple(
        item for item in rb.RECORDED_TOPICS if item.channel_id != "d455.infra2"
    )
    args = s0.realsense_launch_arguments(trimmed)
    assert "enable_infra2:=true" not in args
    assert "enable_infra1:=true" in args
    # ...and the shipped plan still carries it, so the test above is meaningful.
    assert "enable_infra2:=true" in s0.realsense_launch_arguments()


def test_an_unknown_d455_channel_on_the_plan_is_a_refusal_not_a_silent_omission() -> None:
    invented = rb.RecordedTopic(
        "/camera/camera/fisheye/image_raw",
        "sensor_msgs/msg/Image",
        rb.TopicSource.DRIVER_NODE,
        "d455.fisheye",
        rb.Confidence.UNVERIFIED,
        "a stream a later card might add to the plan",
        "ros2 launch realsense2_camera rs_launch.py",
    )
    with pytest.raises(s0.AddendumRefusedError) as caught:
        s0.realsense_launch_arguments((*rb.RECORDED_TOPICS, invented))
    assert "d455.fisheye" in str(caught.value)


def test_the_l2_launch_line_is_read_off_the_plans_own_prerequisite() -> None:
    rows = s0.l2_topics()
    assert rows, "the plan carries no L2 row"
    assert s0.l2_launch_command() == rows[0].prerequisite.strip()
    assert s0.l2_launch_command().startswith("ros2 launch ")


def test_every_planned_topic_of_each_class_appears_in_the_sheet() -> None:
    text = s0.render_addendum(rb.RosDistro.HUMBLE)
    for row in (*s0.d455_topics(), *s0.l2_topics(), *s0.camera_info_topics()):
        assert row.topic in text, f"{row.topic} is recorded but never observed on the sheet"


def test_the_camera_namespace_is_derived_not_typed() -> None:
    namespace, name = s0.camera_identity()
    args = s0.realsense_launch_arguments()
    assert f"camera_namespace:={namespace}" in args
    assert f"camera_name:={name}" in args
    assert s0.d455_topics()[0].topic.startswith(f"/{namespace}/{name}/")


# ---------------------------------------------------------------------------
# Layer 6: the S-1 gate names are real
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("module_name", "symbol", "why"), s0.GATE_REFERENCES)
def test_every_named_stop_gate_exists_in_the_live_module(
    module_name: str, symbol: str, why: str
) -> None:
    """Cross-check against S-1's landed API.

    A rename in S-1's files reddens HERE rather than leaving the operator sheet
    naming a gate that no longer exists.
    """

    module = importlib.import_module(module_name)
    assert hasattr(module, symbol), (
        f"{module_name}.{symbol} is named in T10.7 of the operator sheet but does "
        f"not exist; the sheet promises a gate the code no longer has ({why})"
    )
    assert why.strip()


def test_the_snapshot_schema_named_in_the_sheet_is_the_sidecars_own() -> None:
    sidecar = importlib.import_module("scripts.parcel_capture.sidecar")
    assert s0.STATIC_TF_SNAPSHOT_SCHEMA_NAME == sidecar.STATIC_TF_SNAPSHOT_SCHEMA


@pytest.mark.parametrize("distro", DISTROS)
def test_the_sheet_names_every_gate_it_promises(distro: rb.RosDistro) -> None:
    text = s0.document_path(distro).read_text(encoding="utf-8")
    for module_name, symbol, _why in s0.GATE_REFERENCES:
        assert f"{module_name}.{symbol}" in text


# ---------------------------------------------------------------------------
# Row structure: no prose-only rows, no commanding rows, no stale NIC
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("distro", DISTROS)
def test_every_row_carries_a_command_an_observable_and_a_stop(
    distro: rb.RosDistro,
) -> None:
    rows = s0.build_addendum(distro).all_rows
    assert len(rows) >= 20
    for row in rows:
        assert any(line.strip() for line in row.command), row.row_id
        assert row.expected.strip(), row.row_id
        assert "STOP" in row.stop, row.row_id
        assert row.provenance.strip(), row.row_id


def test_a_row_without_a_stop_branch_cannot_be_constructed() -> None:
    with pytest.raises(s0.AddendumRefusedError) as caught:
        s0.CommandRow(
            row_id="T7.9",
            title="a row somebody wrote in a hurry",
            command=("ros2 topic list",),
            expected="topics appear",
            stop="it should be fine",
            provenance="[CITE] nothing",
        )
    assert "STOP" in str(caught.value)


def test_a_prose_only_row_cannot_be_constructed() -> None:
    with pytest.raises(s0.AddendumRefusedError):
        s0.CommandRow(
            row_id="T7.9",
            title="check the camera",
            command=("", "   "),
            expected="the camera is fine",
            stop="STOP if it is not",
            provenance="[CITE] nothing",
        )


def test_a_row_that_would_command_the_robot_is_refused() -> None:
    with pytest.raises(s0.AddendumRefusedError) as caught:
        s0.CommandRow(
            row_id="T9.9",
            title="generate discovery traffic the easy way",
            command=("ros2 topic pub -r 2 /ping std_msgs/msg/String '{data: ping}'",),
            expected="packets on the NIC",
            stop="STOP if none appear",
            provenance="[CITE] N6d",
        )
    assert "sensors-only" in str(caught.value)


def test_a_row_naming_the_stale_config_interface_is_refused() -> None:
    with pytest.raises(s0.AddendumRefusedError) as caught:
        s0.CommandRow(
            row_id="T9.9",
            title="bind DDS to the NIC in the config file",
            command=(f"sudo ip addr add 192.168.123.222/24 dev {s0.STALE_INTERFACE_NAME}",),
            expected="the address appears",
            stop="STOP if it does not",
            provenance="[REPO] configs/robot.yaml:128",
        )
    assert "configs/robot.yaml" in str(caught.value)


@pytest.mark.parametrize("distro", DISTROS)
def test_no_rendered_command_offers_the_stale_interface_name(distro: rb.RosDistro) -> None:
    for row in s0.build_addendum(distro).all_rows:
        for line in row.command:
            assert s0.STALE_INTERFACE_NAME not in line


@pytest.mark.parametrize("distro", DISTROS)
def test_the_dds_config_forces_the_operator_to_substitute_the_interface(
    distro: rb.RosDistro,
) -> None:
    """The placeholder is only useful if something checks it was replaced."""

    rows = {row.row_id: row for row in s0.build_addendum(distro).all_rows}
    dds = rows["T9.3"]
    body = "\n".join(dds.command)
    assert s0.GO2_IFACE_PLACEHOLDER in body
    assert "sed -i" in body
    assert f"grep -c '{s0.GO2_IFACE_PLACEHOLDER}'" in body
    assert "prints **0**" in dds.expected
    assert "STOP" in dds.stop


# ---------------------------------------------------------------------------
# The draft-until-H-1 contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("distro", DISTROS)
def test_each_sheet_carries_the_draft_banner_and_voids_the_other(
    distro: rb.RosDistro,
) -> None:
    other = rb.RosDistro.JAZZY if distro is rb.RosDistro.HUMBLE else rb.RosDistro.HUMBLE
    text = s0.document_path(distro).read_text(encoding="utf-8")
    assert "DRAFT UNTIL H-1" in text
    assert "NOT YET OPERATIVE" in text
    assert "VOID" in text
    assert Path(s0.DOCUMENT_RELPATHS[other]).name in text
    assert "/etc/nv_tegra_release" in text
    assert "--emit-distro" in text


@pytest.mark.parametrize("distro", DISTROS)
def test_each_sheet_states_plainly_that_nothing_ran_on_an_orin(
    distro: rb.RosDistro,
) -> None:
    text = s0.document_path(distro).read_text(encoding="utf-8")
    assert "has ever executed on a real Orin" in text
    assert "H-1" in text and "H-2" in text


@pytest.mark.parametrize("distro", DISTROS)
def test_each_sheet_carries_all_four_board_rows(distro: rb.RosDistro) -> None:
    text = s0.document_path(distro).read_text(encoding="utf-8")
    for key in s0.SECTION_KEYS:
        assert f"## {key} · " in text
    assert "realsense2_camera" in text
    assert "unite_imu_method" in text
    assert "unitree_lidar_ros2" in text
    assert "CYCLONEDDS_URI" in text
    assert f"source /opt/ros/{distro.value}/setup.bash" in text


@pytest.mark.parametrize("distro", DISTROS)
def test_the_verify_help_row_precedes_the_record_row(distro: rb.RosDistro) -> None:
    """T10.1 is mandatory and must come before the argv the operator types."""

    text = s0.document_path(distro).read_text(encoding="utf-8")
    assert text.index("--verify-help") < text.index(s0.ARGV_BEGIN.format(distro=distro.value))


@pytest.mark.parametrize("distro", DISTROS)
def test_the_storage_config_is_not_inside_the_record_target(distro: rb.RosDistro) -> None:
    """``ros2 bag record`` refuses an --output folder that already exists.

    MEASURED in the repo's ROS 2 Jazzy sandbox — ``ros2bag/verb/record.py``
    lines 273-274, ``if os.path.isdir(uri): return print_error("Output folder
    '{}' already exists.")`` — and executed: the recorder printed
    ``[ERROR] [ros2bag]: Output folder '…' already exists.`` and exited 1.
    Emitting the storage config into the bag directory creates that directory,
    and the recorder then refuses before writing a byte.
    """

    addendum = s0.build_addendum(distro)
    assert addendum.output_dir not in addendum.storage_config_path.parents
    assert addendum.storage_config_path.parent != addendum.output_dir
    text = s0.document_path(distro).read_text(encoding="utf-8")
    assert "already exists" in text


def test_module_is_3_10_parseable() -> None:
    source = Path(s0.__file__).read_text(encoding="utf-8")
    ast.parse(source, filename=s0.__file__, feature_version=(3, 10))


if __name__ == "__main__":
    for _distro in DISTROS:
        print(f"wrote {s0.emit_per_distro_addendum(_distro)}")
