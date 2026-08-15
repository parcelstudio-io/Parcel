"""Run-specific Stage-0 command addendum — card S-2 (T7–T10).

The defect this module exists for
---------------------------------
``STAGE0_RUN_SHEET.md`` §3 historically had no first-class rows for the
RealSense launch, L2 launch, Unitree overlay/DDS environment, or the actual
``ros2 bag record -s mcap`` argv. Operators copied yesterday's sheets, which
still carried ``--disable-keyboard-controls`` — a flag Humble's recorder
rejects with argparse exit 2 and **zero bytes recorded**.

Working agreement 7: one source of recorder argv truth. T10 is therefore
rendered exclusively from :func:`scripts.parcel_capture.rosbag2.record_command`
against a :class:`~scripts.parcel_capture.rosbag2.Rosbag2Plan`. Hand-invented
argv in Markdown is a defect; ``tests/test_stage0_command_addendum.py``
reddens if the committed addendum drifts from this renderer.

H-1 has not run. Distro is unread. This module drafts **both** Humble and
Jazzy templates and marks ``FINALIZE_BLOCKED_ON_H1``. It never claims
``READY_FOR_STATIONARY_STAGE0``.

Exactly one command renderer (AU-F FX-1 / F1)
---------------------------------------------
There used to be two. ``render_stage0_command_addendum()`` rendered a *combined*
review document carrying both distro templates side by side, and
``render_addendum()`` rendered the per-distro operator sheets. Both read the
same plan, so the docstring claimed they could not disagree — and they did:
against different ``output_dir`` / ``storage_config_path`` arguments they
produced 46-vs-46 and 50-vs-50 token argv that differed in the bag directory and
the storage-config path, and the combined document's T7 launch line silently
dropped ``publish_tf:=true`` / ``tf_publish_rate:=0.0``, which S-1's GO-RECORD
gate requires. Three committed sheets, two argv truths.

So now:

* :func:`render_addendum` is the **only** renderer that emits a command. It
  renders the per-distro operator sheet (``STAGE0_ADDENDUM_HUMBLE.md`` /
  ``STAGE0_ADDENDUM_JAZZY.md``). Exactly one becomes operative when H-1 reports
  the observed distro; the other is void and says so in its own banner. Its
  unit is a ROW, not a paragraph: :class:`CommandRow` refuses to exist without
  all three of the exact command, the expected observable, and an explicit STOP
  branch.
* :func:`render_combined_index` renders ``STAGE0_COMMAND_ADDENDUM.md`` as a
  thin **index**: the exactly-one-operative / VOID branch logic and links to
  the two per-distro sheets, and **no command rows at all**. It refuses to
  return a document that contains a command token
  (:data:`_INDEX_FORBIDDEN_TOKENS`), so the second argv truth cannot grow back.

``tests/test_stage0_command_addendum.py`` tokenises every committed sheet and
asserts one argv and one launch line per distro across all of them.

Nothing here writes into the repo tree by default
-------------------------------------------------
:func:`emit_addendum` and :func:`emit_per_distro_addendum` both **require** an
explicit argument, so the no-arm pin's dynamic harness — which calls every
public module-level callable whose parameters all have defaults — cannot reach
them. It used to: ``emit_addendum()`` defaulted to the committed path and
rewrote ``STAGE0_COMMAND_ADDENDUM.md`` mid-suite, healing a hand-edit before
the byte-identity pin read the file (AU-F FX-1 / F3).

Anti-drift, structurally
------------------------
The RealSense launch arguments and every topic name in the per-distro sheet are
**derived from the recording plan itself** (:data:`rosbag2.RECORDED_TOPICS`,
:data:`rosbag2.SUPPORT_TOPICS`): drop ``d455.infra2`` from the plan and
``enable_infra2:=true`` leaves the launch line in the same commit, because both
come from one list. A D455 channel that reaches the plan with no known launch
argument is a **refusal**, not a silent omission — recording a stream nobody
launched yields a topic with no publisher and a bag with an invisible hole.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.parcel_capture.budget import RECOMMENDED_PROFILE, D455Profile
from scripts.parcel_capture.rosbag2 import (
    RECORDED_TOPICS,
    SUPPORT_TOPICS,
    RecordedTopic,
    Rosbag2Plan,
    Rosbag2RefusedError,
    RosDistro,
    plan_for_session,
    preflight_topic_check_command,
    record_command,
    record_help_command,
    storage_config_yaml,
    validate_argv_against_help,
)

#: The bag directory the operator types on the day, and the ONLY one: this is
#: the same value the per-distro operator sheets render (:data:`S2_OUTPUT_DIR`
#: is an alias of it), so no two committed documents can name different record
#: targets. It is deliberately a **per-take** directory rather than a reusable
#: one: ``ros2 bag record`` refuses to start when ``--output`` already exists
#: (MEASURED, Jazzy sandbox: ``[ERROR] [ros2bag]: Output folder … already
#: exists.`` exit 1; ``ros2bag/verb/record.py:273-274``), so a fixed
#: ``/data/parcel/session`` fails on every take after the first.
#:
#: It is NOT the ``rosbag2`` CLI ``--output`` default (that is still
#: ``/data/parcel/session``); the earlier docstring claiming they match was
#: wrong, and the two are not required to agree — the operator sheet is
#: rendered with an explicit ``--output``.
DEFAULT_OUTPUT_DIR = Path("/data/parcel/stage0/take01")

#: Where the rendered MCAP storage config is written on the record target.
#: The argv points here via ``--storage-config-file``.
#: Must sit **outside** :data:`DEFAULT_OUTPUT_DIR` — rosbag2 refuses an
#: already-existing ``--output`` folder, so nesting the config under the bag
#: directory creates that folder and loses the first take (AU-F MAJOR).
#: :func:`refuse_storage_config_inside_output` enforces it structurally rather
#: than trusting these two constants to stay consistent.
DEFAULT_STORAGE_CONFIG_PATH = Path("/data/parcel/stage0/mcap_storage.yaml")

#: Provenance only — do not edit the 20260813 template in place.
HISTORICAL_RUN_SHEET = (
    "scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md"
)
HISTORICAL_CHECKLIST = (
    "scrum/20260813/task_1/session/TONIGHT_CHECKLIST.md"
)

ADDENDUM_RELATIVE = Path("scrum/20260814/task_1/STAGE0_COMMAND_ADDENDUM.md")

#: Marker pairs so the pin can extract rendered argv without guessing.
ARGV_BEGIN = "<!-- BEGIN_ARGV:{distro} -->"
ARGV_END = "<!-- END_ARGV:{distro} -->"
STORAGE_BEGIN = "<!-- BEGIN_STORAGE_CONFIG -->"
STORAGE_END = "<!-- END_STORAGE_CONFIG -->"


def addendum_path(repo_root: Path | None = None) -> Path:
    root = REPO_ROOT if repo_root is None else repo_root
    return root / ADDENDUM_RELATIVE


REPO_ROOT = Path(__file__).resolve().parents[2]


def refuse_storage_config_inside_output(
    output_dir: Path | str, storage_config_path: Path | str
) -> None:
    """Refuse a ``--storage-config-file`` that lives under the ``--output`` folder.

    MEASURED, ROS 2 Jazzy sandbox (``ros2bag/verb/record.py:273-274``
    ``if os.path.isdir(uri): return print_error(...)``)::

        $ python3 -m scripts.parcel_capture.rosbag2 \\
              --emit-storage-config /data/parcel/session/mcap_storage.yaml
        wrote /data/parcel/session/mcap_storage.yaml
        $ ros2 bag record --storage mcap --output /data/parcel/session …
        [ERROR] [ros2bag]: Output folder '/data/parcel/session' already exists.
        exit=1

    Writing the config into the bag directory *creates* the bag directory, and
    the recorder then refuses before a byte is written — the first take is lost
    on the row that was supposed to protect it. This is a construction-time
    refusal so that no renderer, and no caller passing its own paths, can emit
    that ordering. Fail closed: an unresolvable path refuses too.
    """

    output = Path(output_dir)
    storage = Path(storage_config_path)
    if not output.is_absolute() or not storage.is_absolute():
        raise AddendumRefusedError(
            f"output_dir={output} and storage_config_path={storage} must both be "
            f"absolute: the operator types these on a machine whose cwd nobody here "
            f"knows, and a relative record target is a bag written somewhere unread"
        )
    if storage == output or output in storage.parents:
        raise AddendumRefusedError(
            f"storage config {storage} sits inside the record target {output}. "
            f"Emitting it creates that directory, and `ros2 bag record` refuses an "
            f"--output folder that already exists (MEASURED: \"Output folder "
            f"'{output}' already exists.\" exit 1, ros2bag/verb/record.py:273-274) — "
            f"the first take is lost. Put the storage config OUTSIDE the bag "
            f"directory, e.g. {output.parent / storage.name}"
        )


def session_plan(
    *,
    distro: RosDistro,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    storage_config_path: Path = DEFAULT_STORAGE_CONFIG_PATH,
) -> Rosbag2Plan:
    """The plan T10 is rendered from. Distro is an explicit argument — never guessed."""

    refuse_storage_config_inside_output(output_dir, storage_config_path)
    return plan_for_session(
        output_dir,
        storage_config_path=storage_config_path,
        distro=distro,
    )


def rendered_argv(
    distro: RosDistro,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    storage_config_path: Path = DEFAULT_STORAGE_CONFIG_PATH,
) -> tuple[str, ...]:
    """T10 argv for ``distro``. The only legal source for the addendum's T10 rows."""

    return record_command(
        session_plan(
            distro=distro,
            output_dir=output_dir,
            storage_config_path=storage_config_path,
        )
    )


def rendered_argv_line(
    distro: RosDistro,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    storage_config_path: Path = DEFAULT_STORAGE_CONFIG_PATH,
) -> str:
    return " ".join(
        rendered_argv(
            distro,
            output_dir=output_dir,
            storage_config_path=storage_config_path,
        )
    )


def refuse_if_humble_carries_disable_keyboard(argv: Sequence[str]) -> None:
    """Humble must never see ``--disable-keyboard-controls``.

    That flag does not exist on Humble's recorder verb; argparse exits 2 and
    the session records nothing. Fail closed here so a hand-edited or injected
    argv cannot reach the operator sheet.
    """

    if "--disable-keyboard-controls" in argv:
        raise Rosbag2RefusedError(
            "Humble argv must not carry --disable-keyboard-controls; "
            "Humble's ros2 bag record has no keyboard handler and rejects the "
            "flag with argparse exit 2 and ZERO bytes recorded. Build the plan "
            "with RosDistro.HUMBLE (record_command omits the flag) or use Jazzy "
            "only after H-1 confirms /opt/ros/jazzy"
        )


def clear_argv_against_help(
    argv: Sequence[str],
    help_text: str,
    *,
    distro: RosDistro,
) -> tuple[str, ...]:
    """Validate ``argv`` against installed ``ros2 bag record --help``.

    On Humble, additionally refuse the keyboard flag even if a corrupted help
    text somehow listed it — the distro rule is load-bearing independent of
    help parsing.
    """

    if distro is RosDistro.HUMBLE:
        refuse_if_humble_carries_disable_keyboard(argv)
    return validate_argv_against_help(argv, help_text)


def _source_ros(distro: RosDistro) -> str:
    return f"source /opt/ros/{distro.value}/setup.bash"


def _storage_block() -> str:
    body = storage_config_yaml().rstrip("\n")
    return f"{STORAGE_BEGIN}\n```yaml\n{body}\n```\n{STORAGE_END}"


def extract_argv_from_addendum(text: str, distro: RosDistro) -> tuple[str, ...]:
    """Parse a rendered argv block out of addendum markdown. Refuse on absence."""

    begin = ARGV_BEGIN.format(distro=distro.value)
    end = ARGV_END.format(distro=distro.value)
    if begin not in text or end not in text:
        raise Rosbag2RefusedError(
            f"addendum is missing {begin} … {end}; regenerate, do not hand-patch"
        )
    inner = text.split(begin, 1)[1].split(end, 1)[0]
    # Expect a single fenced code block whose body is one argv line.
    if "```" not in inner:
        raise Rosbag2RefusedError(f"argv block for {distro.value} has no fence")
    body = inner.split("```", 2)[1]
    # Drop an optional language tag line.
    lines = [line for line in body.strip("\n").splitlines() if line.strip()]
    if len(lines) != 1:
        raise Rosbag2RefusedError(
            f"argv block for {distro.value} must be exactly one line, got {len(lines)}"
        )
    return tuple(lines[0].split())


def extract_storage_config_from_addendum(text: str) -> str:
    if STORAGE_BEGIN not in text or STORAGE_END not in text:
        raise Rosbag2RefusedError("addendum is missing the storage-config markers")
    inner = text.split(STORAGE_BEGIN, 1)[1].split(STORAGE_END, 1)[0]
    if "```" not in inner:
        raise Rosbag2RefusedError("storage-config block has no fence")
    body = inner.split("```", 2)[1]
    lines = body.splitlines()
    if lines and lines[0].strip() in {"yaml", "yml"}:
        lines = lines[1:]
    return "\n".join(lines).strip("\n") + "\n"


#: Tokens that make a document a *command sheet*. ``STAGE0_COMMAND_ADDENDUM.md``
#: is an index and must contain none of them: the moment it carries a command,
#: it is a second copy of the operator's argv, and two copies drift (F1 —
#: 46-vs-46 / 50-vs-50 tokens differing in the record target and the storage
#: config path, plus a T7 launch line missing ``publish_tf:=true``).
_INDEX_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "ros2 bag record",
    "ros2 launch",
    "ros2 topic",
    "export RMW_IMPLEMENTATION",
    "export CYCLONEDDS_URI",
    "source /opt/ros/",
    "<!-- BEGIN_ARGV",
    STORAGE_BEGIN,
)


def render_combined_index() -> str:
    """``STAGE0_COMMAND_ADDENDUM.md`` — a thin GENERATED index, zero command rows.

    This file used to be the second command renderer, and it disagreed with the
    per-distro operator sheets about the record target, the storage-config path
    and the T7 launch arguments. The AU-F resolution ruling made the per-distro
    pair operative and reduced this document to what only it can carry: the
    exactly-one-operative / VOID branch logic, and links.

    Byte-stable (no timestamps, no probes), and self-checked: a command token
    reaching this text is a refusal, not a rendered document.
    """

    humble = Path(DOCUMENT_RELPATHS[RosDistro.HUMBLE]).name
    jazzy = Path(DOCUMENT_RELPATHS[RosDistro.JAZZY]).name

    out: list[str] = []
    w = out.append
    w("# Stage-0 command addendum — INDEX (2026-08-14, card S-2)")
    w("")
    w("> ## ⚠ GENERATED INDEX — no commands live here")
    w(">")
    w(
        "> This file is rendered by "
        "`scripts/parcel_capture/stage0_addendum.py::render_combined_index()` and "
        "carries **no command rows at all**. Every operator command — the RealSense "
        "launch, the L2 launch, the Unitree overlay/DDS environment and the recorder "
        "argv — lives in exactly one of the two per-distro sheets below, rendered by "
        "the single command renderer `render_addendum()`."
    )
    w(">")
    w(
        "> It used to carry a second copy of those commands. The copies disagreed: "
        "different record target, different storage-config path, and a RealSense "
        "launch line missing the transform arguments S-1's GO-RECORD gate requires. "
        "One renderer now, and `tests/test_stage0_command_addendum.py` tokenises "
        "every committed sheet and fails if two of them spell one distro's argv or "
        "launch line differently."
    )
    w("")
    w("## Which sheet is operative")
    w("")
    w("**Neither, yet.** H-1 has not run: nobody has read the Orin's ROS distro, so")
    w("both sheets carry a DRAFT-UNTIL-H-1 banner and **FINALIZE is blocked**.")
    w("`READY_FOR_STATIONARY_STAGE0` is **not claimed** — that needs H-2 evidence")
    w("from the actual Orin, not a desktop or a sandbox.")
    w("")
    w("Run H-1's identity dump (REVISED_BOARD.md H-1), then branch:")
    w("")
    w("| H-1 reports | Operative sheet | VOID |")
    w("|---|---|---|")
    w(f"| `/opt/ros/humble` | [{humble}]({humble}) | `{jazzy}` |")
    w(f"| `/opt/ros/jazzy` | [{jazzy}]({jazzy}) | `{humble}` |")
    w(
        "| anything else — Foxy, JetPack 5.x, no ROS | **none** | **both** — take "
        "REVISED_BOARD.md H-1's 'anything else' branch: STOP, report the exact "
        "output, retarget |"
    )
    w("")
    w(
        "Exactly one sheet becomes operative. The generator refuses to render an "
        "unknown distro rather than defaulting to a plausible one, so there is no "
        "path by which a Foxy Orin gets handed the Humble sheet."
    )
    w("")
    w("## Regeneration")
    w("")
    w("```")
    w(
        ".parcel/bin/python -m scripts.parcel_capture.stage0_addendum "
        "--distro <H-1's answer> --emit-distro   # the operative sheet"
    )
    w(
        ".parcel/bin/python -m scripts.parcel_capture.stage0_addendum "
        "--emit-all-distros                      # both drafts"
    )
    w(
        ".parcel/bin/python -m scripts.parcel_capture.stage0_addendum "
        "--emit                                  # this index"
    )
    w("```")
    w("")
    w("## Provenance and scope")
    w("")
    w("| Field | Value |")
    w("|---|---|")
    w(
        "| **H-1 Orin identity** | **UNREAD** — `cat /etc/nv_tegra_release`; "
        "`lsb_release -a`; `ls /opt/ros` not yet executed |"
    )
    w("| **Observed ROS distro** | unknown — fail closed |")
    w("| **FINALIZE** | **BLOCKED ON H-1** |")
    w("| **READY_FOR_STATIONARY_STAGE0** | **not claimed** — requires H-2 evidence |")
    w(f"| Plan of record (D455) | `{RECOMMENDED_PROFILE.label}` |")
    w(f"| Record target (both sheets) | `{DEFAULT_OUTPUT_DIR}` |")
    w(
        f"| Storage config (outside the record target) | "
        f"`{DEFAULT_STORAGE_CONFIG_PATH}` |"
    )
    w(f"| Rows covered | {', '.join(SECTION_KEYS)} |")
    w(
        f"| Provenance (immutable) | `{HISTORICAL_RUN_SHEET}`, "
        f"`{HISTORICAL_CHECKLIST}` N2e/N5b/N6/N4 |"
    )
    w("")
    w(
        "Historical 20260813 sheets stay as provenance (working agreement 3). The "
        "per-distro pair supersedes them for the four missing command rows only."
    )
    w("")
    w("## What this index does not know")
    w("")
    w("- Which distro the Orin actually has (H-1 unread) — **FINALIZE blocked**.")
    w(
        "- Whether the driver package names, overlay paths and launch-argument "
        "spellings in the per-distro sheets match what is installed (H-2)."
    )
    w("- Whether the real topic names equal the plan's documentation-derived names.")
    w(
        "- Sustained write rate or free space on the record target (see "
        "`DISK_LEDGER.md`; measure on the Orin)."
    )
    w("- Anything that would authorize motion, stand, gait, or a vendor lease.")
    w("")
    text = "\n".join(out) + "\n"

    found = [token for token in _INDEX_FORBIDDEN_TOKENS if token in text]
    if found:
        raise AddendumRefusedError(
            f"the combined index would carry command token(s) {found}: this file is "
            f"an index, and a command in it is a second argv truth beside the "
            f"per-distro sheets — which is exactly the contradiction AU-F found "
            f"(46-vs-46 / 50-vs-50 argv tokens, and a T7 launch line missing "
            f"publish_tf). Put the command in render_addendum() instead"
        )
    return text


def emit_addendum(path: Path) -> Path:
    """Write the combined index to ``path``. The path is REQUIRED, deliberately.

    It used to default to the committed sheet, and the no-arm pin's dynamic
    harness — which calls every public module-level callable whose parameters
    all have defaults — therefore rewrote ``STAGE0_COMMAND_ADDENDUM.md`` in the
    middle of the test run, healing a hand-edit before the byte-identity pin
    read it. Requiring an argument makes that call unreachable by construction
    rather than by a skip-list somebody has to remember to update.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_combined_index(), encoding="utf-8")
    return target


# ===========================================================================
# The per-distro operator sheet — card S-2's OWNS half
# ===========================================================================
#
# Everything above renders the INDEX. The commands live here, in two SEPARATE
# operator sheets, exactly one of which becomes operative when H-1 reports the
# observed distro. The other is void, and says so in its own banner. At 08:00
# the operator has one Orin, one distro, and no appetite for choosing between
# two code blocks while a battery drains.
#
# The unit here is a ROW, not a paragraph. A row that cannot be passed or
# failed is not a row, so CommandRow refuses to exist without all three of:
# the exact command, the expected observable, and the STOP branch.


class AddendumRefusedError(Rosbag2RefusedError):
    """The per-distro sheet cannot be rendered as asked. Never a default."""


#: Record target for the per-distro sheet. Deliberately a per-take directory:
#: ``ros2 bag record`` REFUSES to start when its ``--output`` path already
#: exists, so the record target must be a name that does not yet exist when the
#: recorder is launched.
#:
#: MEASURED, in the repo's ROS 2 Jazzy sandbox, in the recorder verb's own
#: source: ``ros2bag/verb/record.py:273-274`` ::
#:
#:     if os.path.isdir(uri):                                   # record.py:273
#:         return print_error("Output folder '{}' already exists.".format(uri))
#:
#: This is an **alias** of :data:`DEFAULT_OUTPUT_DIR`, not a second value. Two
#: independently-maintained record targets is precisely how the combined sheet
#: and the per-distro sheets came to disagree (F1).
S2_OUTPUT_DIR = DEFAULT_OUTPUT_DIR

#: The ``--storage-config-file`` for the per-distro sheet, and it is
#: **deliberately NOT under** :data:`S2_OUTPUT_DIR`. Emitting the storage config
#: into the bag directory creates that directory, and the ``os.path.isdir``
#: check above then refuses the recording before a byte is written. The sheet's
#: T10.2 row emits it here and T10.5 verifies the output directory is absent.
#: An **alias** of :data:`DEFAULT_STORAGE_CONFIG_PATH`, for the same reason.
S2_STORAGE_CONFIG_PATH = DEFAULT_STORAGE_CONFIG_PATH

#: Where the operator saves ``ros2 bag record --help`` for the clearance row.
RECORD_HELP_PATH = "/tmp/parcel_record_help.txt"

#: Where the observed graph is captured for the S-1 support reconciliation.
TOPIC_LIST_PATH = "/tmp/parcel_topic_list.txt"

#: The interface names are **placeholders the operator must replace**, and they
#: are deliberately unusable as typed: a command still carrying one fails
#: loudly instead of binding DDS to a NIC nobody chose, which is the classic
#: silent zero-topics failure.
GO2_IFACE_PLACEHOLDER = "__GO2_IFACE__"
L2_IFACE_PLACEHOLDER = "__L2_IFACE__"

#: ``configs/robot.yaml:128`` and ``:342`` both carry this name. It is a
#: placeholder from a different machine and has never been observed on the
#: Orin. No rendered command may contain it — :func:`_refuse_stale_interface`
#: enforces that, so a copy-paste of the config value cannot become a command.
STALE_INTERFACE_NAME = "enp3s0"

#: Addresses, single-sourced here so the T8/T9 rows cannot drift from
#: ``session/TONIGHT_CHECKLIST.md`` N6b, which is where they were decided.
GO2_LAN_ADDRESS = "192.168.123.222/24"
L2_HOST_ADDRESS = "192.168.1.1/24"
L2_DEVICE_ADDRESS = "192.168.1.2"

#: The security pin that gates every LAN join (ADR 0002 §1, PRE-1).
FIRMWARE_PIN = "V1.1.13"

#: Where each per-distro sheet lives.
DOCUMENT_RELPATHS: Mapping[RosDistro, str] = {
    RosDistro.HUMBLE: "scrum/20260814/task_1/STAGE0_ADDENDUM_HUMBLE.md",
    RosDistro.JAZZY: "scrum/20260814/task_1/STAGE0_ADDENDUM_JAZZY.md",
}

#: The four rows REVISED_BOARD.md S-2 names, in execution order.
SECTION_KEYS: tuple[str, ...] = ("T7", "T8", "T9", "T10")


def parse_distro(value: RosDistro | str) -> RosDistro:
    """``"humble"`` / ``"jazzy"`` / a :class:`RosDistro`, or a refusal.

    Unknown is **not** defaulted. H-1's "anything else" branch (Foxy, JetPack
    5.x, no ROS) is a STOP that voids both variants of this addendum, and a
    generator that quietly rendered the Humble sheet for a Foxy Orin would hand
    the operator a command line that distro's argparse rejects — exit 2, zero
    bytes, at the robot.
    """

    if isinstance(value, RosDistro):
        return value
    if not isinstance(value, str):
        raise AddendumRefusedError(
            f"distro must be a RosDistro or one of "
            f"{[item.value for item in RosDistro]}, got {type(value).__name__}"
        )
    folded = value.strip().casefold()
    for item in RosDistro:
        if folded == item.value:
            return item
    raise AddendumRefusedError(
        f"unknown ROS distro {value!r}; this addendum is rendered only for "
        f"{[item.value for item in RosDistro]}. If H-1's identity dump reported "
        f"anything else, BOTH variants are VOID: take REVISED_BOARD.md H-1's "
        f"'anything else' branch, STOP, and report the exact output. The "
        f"recorder argv and every launch line retarget to what is actually "
        f"installed; guessing the CLI is how a session records zero bytes"
    )


def document_path(distro: RosDistro | str, root: Path | None = None) -> Path:
    """Absolute path of the per-distro sheet."""

    resolved = parse_distro(distro)
    base = REPO_ROOT if root is None else Path(root)
    return base / DOCUMENT_RELPATHS[resolved]


# ---------------------------------------------------------------------------
# Row / section model
# ---------------------------------------------------------------------------

#: Verbs that would make a rendered row COMMAND something rather than observe
#: it. The recursive no-arm pin covers this module's *code*; this covers the
#: *text* it emits, which the pin cannot read. A session sheet is an
#: instruction to a human, and an instruction to a human is a command surface.
_COMMANDING_TOKENS: tuple[str, ...] = (
    "topic pub",
    "service call",
    "action send",
    "lifecycle set",
    "param set",
)


def _refuse_commanding(row_id: str, line: str) -> None:
    folded = line.casefold()
    for token in _COMMANDING_TOKENS:
        if token in folded:
            raise AddendumRefusedError(
                f"row {row_id!r} would have the operator run {token!r}: this "
                f"session is sensors-only and every row here observes, launches "
                f"a vendor sensor driver, or records. Observe the graph instead"
            )


def _refuse_stale_interface(row_id: str, line: str) -> None:
    if STALE_INTERFACE_NAME in line:
        raise AddendumRefusedError(
            f"row {row_id!r} names {STALE_INTERFACE_NAME!r}, the stale placeholder "
            f"in configs/robot.yaml:128 and :342 — a NIC name from a different "
            f"machine that has never been observed on the Orin. The operator fills "
            f"the real name from `ip -brief addr`; the sheet must not offer a "
            f"plausible wrong one"
        )


@dataclass(frozen=True)
class CommandRow:
    """One operator row: the exact command, the observable, and the STOP branch.

    All three are mandatory. A row with no command is prose; a row with no
    observable cannot be passed or failed; a row with no STOP branch says
    nothing about the morning it goes wrong, which is the only morning the
    sheet is read.
    """

    row_id: str
    title: str
    #: Shell lines, verbatim, in order. Blank entries are formatting.
    command: tuple[str, ...]
    #: What the machine must show if the row passed.
    expected: str
    #: What to do when it does not. Must name the STOP explicitly.
    stop: str
    #: DERIVED (from code), MEASURED, a cited sheet, or UNVERIFIED-SYNTAX. An
    #: unlabelled command is a guess with a monospace font.
    provenance: str
    #: Wrap this row's command block in the ARGV markers so the pin can extract
    #: the argv back OUT of the committed markdown.
    argv_markers: bool = False

    def __post_init__(self) -> None:
        for name, text in (
            ("row_id", self.row_id),
            ("title", self.title),
            ("expected", self.expected),
            ("stop", self.stop),
            ("provenance", self.provenance),
        ):
            if not isinstance(text, str) or not text.strip():
                raise AddendumRefusedError(f"row {self.row_id!r}: {name} must be non-empty")
        if not any(line.strip() for line in self.command):
            raise AddendumRefusedError(
                f"row {self.row_id!r}: a row with no command is prose, and a prose "
                f"row cannot be passed or failed at 08:00"
            )
        if "STOP" not in self.stop:
            raise AddendumRefusedError(
                f"row {self.row_id!r}: the failure branch must name the STOP in "
                f"words the operator can act on, not describe a mood"
            )
        for line in self.command:
            _refuse_commanding(self.row_id, line)
            _refuse_stale_interface(self.row_id, line)


@dataclass(frozen=True)
class Section:
    """One card row of the sheet: T7, T8, T9 or T10."""

    key: str
    title: str
    purpose: str
    rows: tuple[CommandRow, ...]
    appendix: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rows:
            raise AddendumRefusedError(f"section {self.key}: no rows")
        if not self.purpose.strip():
            raise AddendumRefusedError(f"section {self.key}: purpose must be non-empty")
        seen: set[str] = set()
        for row in self.rows:
            if not row.row_id.startswith(self.key + "."):
                raise AddendumRefusedError(
                    f"row {row.row_id!r} does not belong to section {self.key}"
                )
            if row.row_id in seen:
                raise AddendumRefusedError(f"duplicate row id {row.row_id!r}")
            seen.add(row.row_id)


@dataclass(frozen=True)
class Addendum:
    """The whole per-distro sheet before rendering.

    Construction is the gate: every ``ros2 bag record`` line in every row is
    checked against that distro's own recorder CLI here, so a flag the distro
    lacks cannot reach the rendered document at all.
    """

    distro: RosDistro
    output_dir: Path
    storage_config_path: Path
    sections: tuple[Section, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.distro, RosDistro):
            raise AddendumRefusedError(
                f"distro must be a RosDistro, got {self.distro!r}; see parse_distro"
            )
        refuse_storage_config_inside_output(self.output_dir, self.storage_config_path)
        keys = tuple(section.key for section in self.sections)
        if keys != SECTION_KEYS:
            raise AddendumRefusedError(
                f"the sheet must carry exactly {list(SECTION_KEYS)} in order, got "
                f"{list(keys)} — these are the four rows REVISED_BOARD.md S-2 names, "
                f"and a missing one is the gap this card exists to close"
            )
        for section in self.sections:
            for row in section.rows:
                for line in row.command:
                    check_recorder_line(line, self.distro, where=row.row_id)

    @property
    def all_rows(self) -> tuple[CommandRow, ...]:
        return tuple(row for section in self.sections for row in section.rows)


_RECORDER_PREFIX = "ros2 bag record"


def check_recorder_line(
    line: str, distro: RosDistro | str, *, where: str = "<row>"
) -> tuple[str, ...]:
    """Refuse a ``ros2 bag record`` line carrying a flag this distro lacks.

    This is the gate that catches an injected ``--disable-keyboard-controls``
    in the **humble** sheet HERE, in Python, on this desktop, **before a byte of
    Markdown is rendered** — rather than by argparse on the Orin at 08:00,
    which exits 2 and records nothing (PS-M F3).

    Support is decided by :meth:`rosbag2.Rosbag2Plan.supports`, so this module
    holds no second opinion about which flag exists where.
    """

    resolved = parse_distro(distro)
    stripped = line.strip()
    if not stripped.startswith(_RECORDER_PREFIX):
        return ()
    probe = plan_for_session(S2_OUTPUT_DIR, distro=resolved)
    flags = tuple(
        token for token in stripped.replace("\\", " ").split() if token.startswith("--")
    )
    unsupported = [flag for flag in flags if not probe.supports(flag)]
    if unsupported:
        raise AddendumRefusedError(
            f"{where}: `ros2 bag record` line carries {unsupported}, which ROS 2 "
            f"{resolved.value}'s recorder verb does not declare. argparse exits 2 on "
            f"an unrecognised option and the session records ZERO bytes. Render the "
            f"argv from Rosbag2Plan(distro={resolved.value!r}); do not edit the "
            f"command line"
        )
    return flags


# ---------------------------------------------------------------------------
# Derivations from the recording plan — the anti-drift half
# ---------------------------------------------------------------------------

#: Channel id -> the ``rs_launch.py`` argument that makes that stream exist.
#: A D455 channel reaching the plan without an entry here is a REFUSAL, not a
#: silent omission: an unlaunched stream is a topic the recorder subscribes to
#: and never receives, which is invisible until the bag is opened.
_D455_LAUNCH_ENABLE: Mapping[str, str] = {
    "d455.color": "enable_color",
    "d455.depth": "enable_depth",
    "d455.infra1": "enable_infra1",
    "d455.infra2": "enable_infra2",
    "d455.accel": "enable_accel",
    "d455.gyro": "enable_gyro",
}


def d455_topics(topics: Sequence[RecordedTopic] = RECORDED_TOPICS) -> tuple[RecordedTopic, ...]:
    """Every D455 payload row of the recording plan, in plan order."""

    return tuple(
        item for item in topics if item.channel_id and item.channel_id.startswith("d455.")
    )


def l2_topics(topics: Sequence[RecordedTopic] = RECORDED_TOPICS) -> tuple[RecordedTopic, ...]:
    """Every add-on L2 payload row of the recording plan, in plan order."""

    return tuple(
        item for item in topics if item.channel_id and item.channel_id.startswith("l2.")
    )


def camera_info_topics(
    support: Sequence[RecordedTopic] = SUPPORT_TOPICS,
) -> tuple[RecordedTopic, ...]:
    """S-1's CameraInfo support rows, which the T7 launch must produce."""

    return tuple(item for item in support if item.topic.endswith("/camera_info"))


def transform_topics(
    support: Sequence[RecordedTopic] = SUPPORT_TOPICS,
) -> tuple[RecordedTopic, ...]:
    """S-1's ``/tf`` and ``/tf_static`` support rows."""

    return tuple(item for item in support if item.topic in ("/tf", "/tf_static"))


def camera_identity(topics: Sequence[RecordedTopic] = RECORDED_TOPICS) -> tuple[str, str]:
    """``(camera_namespace, camera_name)`` read off the plan's D455 topic names.

    ``/camera/camera/color/image_raw`` decomposes as
    ``/<namespace>/<name>/<stream>/<leaf>``. Deriving the launch arguments from
    the recorded names — rather than typing them a second time — is what makes
    the driver command and the recorder topic list unable to disagree. A plan
    whose D455 rows do not share one ``<namespace>/<name>`` is refused: no
    single launch produces them.
    """

    rows = d455_topics(topics)
    if not rows:
        raise AddendumRefusedError(
            "the recording plan carries no d455.* row, so there is no camera to "
            "launch; a T7 row rendered against an empty plan would be fiction"
        )
    prefixes: set[tuple[str, str]] = set()
    for row in rows:
        parts = row.topic.strip("/").split("/")
        if len(parts) != 4:
            raise AddendumRefusedError(
                f"{row.topic}: expected /<namespace>/<name>/<stream>/<leaf>; "
                f"camera_namespace/camera_name cannot be derived from a name of "
                f"this shape, and guessing them produces a driver publishing under "
                f"topics the recorder never subscribes to"
            )
        prefixes.add((parts[0], parts[1]))
    if len(prefixes) != 1:
        raise AddendumRefusedError(
            f"the plan's D455 rows sit under more than one namespace/name "
            f"({sorted(prefixes)}); one `ros2 launch` cannot produce them all"
        )
    return next(iter(prefixes))


def realsense_launch_arguments(
    topics: Sequence[RecordedTopic] = RECORDED_TOPICS,
    profile: D455Profile = RECOMMENDED_PROFILE,
) -> tuple[str, ...]:
    """The ``rs_launch.py`` arguments that produce exactly the planned streams.

    Every ``enable_*`` here exists because a topic on the recording plan needs
    it, and the profile strings carry :data:`budget.RECOMMENDED_PROFILE` rather
    than a literal. There is no path by which the launch line enables a stream
    the recorder does not record, or omits one it does.
    """

    rows = d455_topics(topics)
    channel_ids = [row.channel_id for row in rows if row.channel_id]
    unknown = sorted(set(channel_ids) - set(_D455_LAUNCH_ENABLE))
    if unknown:
        raise AddendumRefusedError(
            f"the recording plan carries D455 channel(s) {unknown} with no known "
            f"rs_launch.py argument. Recording a stream nobody launched yields a "
            f"topic with no publisher and a bag with a silent hole; add the "
            f"argument to _D455_LAUNCH_ENABLE once it has been read off "
            f"`ros2 launch realsense2_camera rs_launch.py --show-args`"
        )
    namespace, name = camera_identity(topics)
    geometry = f"{profile.width}x{profile.height}x{profile.fps}"
    args: list[str] = [f"camera_namespace:={namespace}", f"camera_name:={name}"]
    for channel_id, argument in _D455_LAUNCH_ENABLE.items():
        if channel_id in channel_ids:
            args.append(f"{argument}:=true")
    if "d455.color" in channel_ids:
        args.append(f"rgb_camera.color_profile:={geometry}")
    if "d455.depth" in channel_ids:
        args.append(f"depth_module.depth_profile:={geometry}")
    if "d455.infra1" in channel_ids or "d455.infra2" in channel_ids:
        args.append(f"depth_module.infra_profile:={geometry}")
    if "d455.accel" in channel_ids and "d455.gyro" in channel_ids:
        # rosbag2.py's own note on the accel row: "unite_imu_method must be set
        # or the IMU topics do not appear." A silent loss, not an error.
        args.append("unite_imu_method:=linear_interpolation")
    # The transform arguments are why /tf_static carries the camera frames at
    # all; S-1's GO-RECORD gate refuses a bag whose optical frames have no
    # parent. A rate of 0.0 means static-only, which is what a rigid mount
    # wants and what keeps the topic latched rather than streaming.
    args.append("publish_tf:=true")
    args.append("tf_publish_rate:=0.0")
    return tuple(args)


def l2_launch_command(topics: Sequence[RecordedTopic] = RECORDED_TOPICS) -> str:
    """The L2 driver launch line, read off the plan rows' own prerequisite.

    ``rosbag2.RecordedTopic.prerequisite`` already states what must be running
    for the topic to exist. Reading it here rather than retyping it means the
    L2 row of the sheet and the L2 rows of the recording plan move together.
    """

    rows = l2_topics(topics)
    if not rows:
        raise AddendumRefusedError(
            "the recording plan carries no l2.* row; there is no add-on LiDAR to "
            "launch and the two-LiDAR cross-validation asset does not exist"
        )
    declared = {row.prerequisite.strip() for row in rows}
    if len(declared) != 1:
        raise AddendumRefusedError(
            f"the plan's L2 rows declare {len(declared)} different prerequisites "
            f"({sorted(declared)}); one launch line cannot be derived from two"
        )
    command = next(iter(declared))
    if not command.startswith("ros2 launch "):
        raise AddendumRefusedError(
            f"the L2 rows' prerequisite is {command!r}, which is not a `ros2 launch` "
            f"line; the SDK example is not the session path (TONIGHT_CHECKLIST N5b) "
            f"and a sheet that offered it would record nothing from the L2"
        )
    return command


# ---------------------------------------------------------------------------
# The S-1 gates this sheet points at, by their real symbol names
# ---------------------------------------------------------------------------

#: ``(module, symbol, what refusing it prevents)``. Cross-checked against the
#: live modules by ``tests/test_stage0_addendum.py``, so a rename in S-1's
#: files reddens here instead of leaving the operator sheet naming a gate that
#: no longer exists.
GATE_REFERENCES: tuple[tuple[str, str, str], ...] = (
    (
        "scripts.parcel_capture.preflight",
        "reconcile_support_topics_or_raise",
        ("a REQUIRED CameraInfo/tf_static topic missing or type-mismatched on the "
        "observed graph refuses BEFORE the recorder starts"),
    ),
    (
        "scripts.parcel_capture.sidecar",
        "validate_static_transform_snapshot",
        ("the transient-local /tf_static captured before record start is a "
        "machine-readable snapshot or it is nothing; prose is not a snapshot"),
    ),
    (
        "scripts.parcel_capture.sidecar",
        "assess_go_record",
        ("an optical stream with no matching intrinsics, a mismatched calibration "
        "profile, or an ambiguous transform tree cannot certify"),
    ),
    (
        "scripts.parcel_capture.sidecar",
        "verify_calibration_digest",
        ("the calibration bound to the manifest is re-derived from the bag's own "
        "CameraInfo bytes; one perturbed byte names itself"),
    ),
    (
        "scripts.parcel_capture.sidecar",
        "verify_sync_fit_binding",
        ("a cross-device time claim is the session's fit only when a digest says "
        "so; a fit supplied after the fact is not evidence"),
    ),
    (
        "scripts.parcel_capture.sidecar",
        "finalize_rosbag2",
        ("with require_go_record=True a refused bag writes NO certified manifest, "
        "not even transiently"),
    ),
)

#: Wire identifier the T10.4 snapshot row must produce. Compared against
#: ``sidecar.STATIC_TF_SNAPSHOT_SCHEMA`` by the test.
STATIC_TF_SNAPSHOT_SCHEMA_NAME = "parcel.capture.static_tf_snapshot.v1"


def _recorder_provenance(distro: RosDistro) -> str:
    if distro is RosDistro.JAZZY:
        return (
            "[DERIVED from Rosbag2Plan(distro=jazzy)] · flags [MEASURED] against a "
            "real `ros2 bag record --help` executed in the repo's ROS 2 Jazzy "
            "sandbox (rosbag2 0.26.11)"
        )
    return (
        "[DERIVED from Rosbag2Plan(distro=humble)] · flags [SOURCE] from "
        "ros2/rosbag2 `ros2bag/verb/record.py` on branch humble and tags "
        "0.15.13/0.15.14/0.15.16 — NOT executed on Humble by anyone"
    )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _t7_section(distro: RosDistro) -> Section:
    rows = d455_topics()
    infos = camera_info_topics()
    args = realsense_launch_arguments()
    launch_lines = ["ros2 launch realsense2_camera rs_launch.py \\"]
    for index, arg in enumerate(args):
        tail = "" if index == len(args) - 1 else " \\"
        launch_lines.append(f"  {arg}{tail}")
    image_rows = [row for row in rows if row.message_type.endswith("/Image")]
    imu_rows = [row for row in rows if row.message_type.endswith("/Imu")]
    profile_label = (
        f"{RECOMMENDED_PROFILE.width}x{RECOMMENDED_PROFILE.height}@{RECOMMENDED_PROFILE.fps}"
    )

    listed = [row.topic for row in rows] + [row.topic for row in infos]
    check_lines = [_source_ros(distro), "for t in \\"]
    for index, topic in enumerate(listed):
        tail = "" if index == len(listed) - 1 else " \\"
        check_lines.append(f"  {topic}{tail}")
    check_lines.append("; do")
    check_lines.append('  echo "===== $t"; ros2 topic type "$t" 2>&1')
    check_lines.append('  timeout 15 ros2 topic hz -w 100 "$t" 2>&1 | tail -3')
    check_lines.append("done")

    first_info = infos[0].topic if infos else "/camera/camera/color/camera_info"
    return Section(
        key="T7",
        title="RealSense D455 driver launch",
        purpose=(
            "The six D455 payload topics are 89.0% of the byte budget and the four "
            "`camera_info` topics are what make them usable afterwards. Nothing on any "
            "sheet has ever launched the node that produces them. Every `enable_*` "
            "argument below is DERIVED from the recording plan's own D455 rows, so the "
            "driver cannot enable a stream the recorder does not record, or omit one it "
            "does."
        ),
        rows=(
            CommandRow(
                row_id="T7.1",
                title="Free the camera before the driver opens it",
                command=(
                    "pkill -f 'python3 -' || true",
                    "lsof /dev/video* 2>/dev/null || echo '(no process holds a video node)'",
                ),
                expected=(
                    "No process holds `/dev/video*`. The D455 is one USB device and only "
                    "one process can own it."
                ),
                stop=(
                    "If a `pyrealsense2` bench script is still running, the driver's "
                    "'failed to open device' is that script, not the camera. STOP, kill "
                    "it, and re-run this row before T7.3 — do not diagnose hardware on a "
                    "device somebody else has open."
                ),
                provenance="[CITE] session/TONIGHT_CHECKLIST.md N2e ⚠ FREE THE CAMERA FIRST",
            ),
            CommandRow(
                row_id="T7.2",
                title="Read the driver's own argument spelling — MANDATORY before T7.3",
                command=(
                    _source_ros(distro),
                    "ros2 launch realsense2_camera rs_launch.py --show-args | head -80",
                ),
                expected=(
                    "A list of launch arguments containing EITHER the "
                    "`<module>.<stream>_profile` form used in T7.3 (driver 4.55-era) OR "
                    "the older `color_width` / `color_height` / `color_fps` and "
                    "`depth_width` / `depth_height` / `depth_fps` form (4.51-era). "
                    "Whichever it prints is the truth; record the substitution."
                ),
                stop=(
                    "Neither form appears, or the launch file is absent: STOP — the "
                    "installed driver is not one this sheet was written against. Record "
                    "the printed argument list verbatim into the run sheet and re-derive "
                    "T7.3 from it. Do not launch on a hunch: a rejected argument is a "
                    "driver at the wrong profile or no driver at all, and the profile is "
                    "what the whole disk budget is sized on."
                ),
                provenance=(
                    "[MEASURED-JAZZY-SANDBOX] `ros2 launch -s/--show-args/--show-arguments` "
                    "exists · [CITE] TONIGHT_CHECKLIST N2e-2 · [UNVERIFIED-SYNTAX] on the "
                    "profile-argument spelling"
                ),
            ),
            CommandRow(
                row_id="T7.3",
                title=f"Launch at the plan of record ({profile_label}, colour+depth+IR pair+IMU)",
                command=(_source_ros(distro), *launch_lines),
                expected=(
                    "The node starts and stays up. Every `enable_*` above exists because a "
                    f"topic on the recording plan needs it: {len(image_rows)} image "
                    f"stream(s) and {len(imu_rows)} IMU stream(s). `unite_imu_method` is "
                    "not optional — without it the accel and gyro topics are simply "
                    "absent and the bag has no D455 inertial data, silently. "
                    "`publish_tf:=true tf_publish_rate:=0.0` is what puts the camera's own "
                    "frames on `/tf_static`, which S-1's GO-RECORD gate requires."
                ),
                stop=(
                    "Node will not start, or cannot open the device: STOP and re-run T7.1 "
                    "before concluding anything about the camera. An argument the driver "
                    "rejects: STOP and return to T7.2 — use the spelling `--show-args` "
                    "printed, never this line as-is."
                ),
                provenance=(
                    "[DERIVED] enable_* set and the topic namespace from "
                    "rosbag2.RECORDED_TOPICS; the profile from budget.RECOMMENDED_PROFILE "
                    "· [UNVERIFIED-SYNTAX] argument spelling, gated by T7.2"
                ),
            ),
            CommandRow(
                row_id="T7.4",
                title="The topics, their types and their rates — including camera_info",
                command=tuple(check_lines),
                expected=(
                    f"All {len(rows) + len(infos)} topics exist. The {len(image_rows)} image "
                    "topics report ≈30 Hz; accel and gyro report whatever the driver united "
                    f"them at (use the reported rate, do not assume); the {len(infos)} "
                    "`camera_info` topics carry `sensor_msgs/msg/CameraInfo`."
                ),
                stop=(
                    "A topic name that differs from this list is a FINDING, not a failure — "
                    "record the real name; a recorder given a name nothing publishes "
                    "subscribes to nothing and reports no error. Do not proceed to T10 with "
                    "a mismatch unrecorded: STOP and correct the plan first, because the "
                    "omission is invisible until the bag is opened. `camera_info` absent on "
                    "any active optical stream: STOP — T10.7's GO-RECORD gate will refuse "
                    "the bag anyway, and finding that out after the take costs the take."
                ),
                provenance=(
                    "[DERIVED] topic list from rosbag2.RECORDED_TOPICS + "
                    "rosbag2.SUPPORT_TOPICS · [MEASURED-JAZZY-SANDBOX] `ros2 topic hz -w` "
                    "and `ros2 topic type` accept these arguments"
                ),
            ),
            CommandRow(
                row_id="T7.5",
                title="The calibration actually describes the stream being recorded",
                command=(
                    _source_ros(distro),
                    f"timeout 10 ros2 topic echo --once {first_info} 2>&1 | head -20",
                ),
                expected=(
                    f"`width: {RECOMMENDED_PROFILE.width}` and "
                    f"`height: {RECOMMENDED_PROFILE.height}`, matching the profile T7.3 "
                    "launched, plus a non-empty distortion model and a `k` matrix that is "
                    "not all zeros."
                ),
                stop=(
                    "A 1280x720 calibration under an 848x480 stream is a calibration for a "
                    "stream that was not recorded. STOP: relaunch at one profile or record "
                    "at the other. This exact mismatch is a named S-1 refusal, and left "
                    "alone it refuses the bag after the take instead of before it."
                ),
                provenance=(
                    "[DERIVED] profile from budget.RECOMMENDED_PROFILE; topic from "
                    "rosbag2.SUPPORT_TOPICS · [MEASURED-JAZZY-SANDBOX] `ros2 topic echo "
                    "--once` exists"
                ),
            ),
        ),
    )


def _t8_section(distro: RosDistro) -> Section:
    rows = l2_topics()
    launch = l2_launch_command()
    topic_lines = [
        _source_ros(distro),
        "ros2 topic list | grep -iE 'unilidar|lidar'",
        "for t in \\",
    ]
    for index, row in enumerate(rows):
        tail = "" if index == len(rows) - 1 else " \\"
        topic_lines.append(f"  {row.topic}{tail}")
    topic_lines.append("; do")
    topic_lines.append('  echo "===== $t"; ros2 topic type "$t" 2>&1')
    topic_lines.append('  timeout 15 ros2 topic hz -w 50 "$t" 2>&1 | tail -3')
    topic_lines.append("done")
    return Section(
        key="T8",
        title="Add-on Unitree L2 driver launch",
        purpose=(
            "The add-on L2 is a different SDK and a different transport from the dog's "
            "built-in unit, and the two LiDARs at a measured relative extrinsic are the "
            "session's cross-validation asset — unrecoverable once the bracket comes off. "
            "The vendor SDK example prints a cloud to a terminal; it does not publish a "
            "topic, and `ros2 bag record` records topics. This section is the ROS node, "
            "which is the session path."
        ),
        rows=(
            CommandRow(
                row_id="T8.1",
                title="Second-NIC preconditions — do these BEFORE anything else in T8",
                command=(
                    "ip -brief addr",
                    "ip route",
                    f"ping -c 3 {L2_DEVICE_ADDRESS}",
                ),
                expected=(
                    f"The L2 NIC (or alias) carries `{L2_HOST_ADDRESS}`, the L2 answers at "
                    f"`{L2_DEVICE_ADDRESS}`, and `ip route` shows **no `default` via the L2 "
                    "interface**. These are TONIGHT_CHECKLIST N6a/N6b's values, not new "
                    "ones; N5's own ordering note applies — the address this ping needs is "
                    "assigned in N6b, which sits later on that sheet than N5."
                ),
                stop=(
                    "No second Ethernet interface at all (most Orin NX carriers have one): "
                    "STOP and take one of N6a's three recorded branches — USB-Ethernet "
                    "adapter, an IP alias on the single NIC, or the `/dev/ttyACM0` serial "
                    "path — and write down which. L2 unreachable: STOP, re-check N6b, and "
                    "record the address it actually answers on; the factory address may "
                    "differ. A `default` route via the L2 NIC: STOP — that is the "
                    "192.168.1.0/24 collision the risk assessment names, and it routes "
                    "robot traffic to a house network."
                ),
                provenance=(
                    "[CITE] session/TONIGHT_CHECKLIST.md N6a/N6b (addresses, "
                    "no-default-route rule) and N5a (the ping, and the N6-before-N5 "
                    "ordering note)"
                ),
            ),
            CommandRow(
                row_id="T8.2",
                title="Source the L2 workspace overlay and confirm the package exists",
                command=(
                    _source_ros(distro),
                    "source ~/unilidar_sdk2/unitree_lidar_ros2/install/setup.bash",
                    "ros2 pkg list | grep -i unitree",
                ),
                expected=(
                    "The L2 ROS package appears. The workspace directory, package name and "
                    "launch-file name all differ between SDK revisions; the SDK's own "
                    "README is authoritative and the path above is the shape N5b recorded."
                ),
                stop=(
                    "Package absent or the overlay path differs: STOP and read the SDK "
                    "README; record the real workspace path. If `colcon build` never "
                    "succeeded, the L2 has no path into the bag at all and the two-LiDAR "
                    "extrinsic is not captured. Write that acceptance down now — not after "
                    "the bracket is torqued."
                ),
                provenance="[CITE] TONIGHT_CHECKLIST N5b · [UNVERIFIED-SYNTAX] on all three names",
            ),
            CommandRow(
                row_id="T8.3",
                title="Launch the L2 node with the transport configured, not defaulted",
                command=(_source_ros(distro), launch),
                expected=(
                    "The node starts and stays up. Its launch file carries the IP/port or "
                    "the serial device and it must match what T8.1 established — configure "
                    "the transport before launching; do not launch with factory defaults "
                    "and hope."
                ),
                stop=(
                    "Node launches but publishes nothing: STOP — the transport parameters "
                    "do not match the device. If the SDK example reads the L2 and the ROS "
                    "node does not, it is configuration, not hardware."
                ),
                provenance=(
                    "[DERIVED] launch line read off rosbag2.RECORDED_TOPICS' own "
                    "`prerequisite` field for the l2.* rows · [UNVERIFIED-SYNTAX]"
                ),
            ),
            CommandRow(
                row_id="T8.4",
                title="The L2 topics, their types and their rates",
                command=tuple(topic_lines),
                expected=(
                    "`/unilidar/cloud` at ≈10-20 Hz carrying `sensor_msgs/msg/PointCloud2`; "
                    "`/unilidar/imu` at ≈200 Hz carrying `sensor_msgs/msg/Imu`. Apply the "
                    "bench IMU plausibility gate: |accel| = 9.81 ± 1, |gyro| < 0.05 at rest. "
                    "Absurd values are DEGRADED, never PRESENT."
                ),
                stop=(
                    "Topic names differ from these: record the real names and STOP before "
                    "T10 — the recorder subscribes to the planned names and says nothing "
                    "when they do not exist. Both topics absent: STOP; the L2 is a "
                    "`parcel-capture`-only channel for this session, which is a second "
                    "artifact in a format no downstream tool reads. Record that acceptance."
                ),
                provenance=(
                    "[DERIVED] topic list from rosbag2.RECORDED_TOPICS l2.* rows · [CITE] "
                    "TONIGHT_CHECKLIST N5b for the expected rates and N5a for the IMU "
                    "plausibility gate"
                ),
            ),
        ),
    )


def _t9_section(distro: RosDistro) -> Section:
    xml_lines = [
        "cat > ~/cyclonedds.xml <<'XML'",
        '<?xml version="1.0" encoding="UTF-8" ?>',
        '<CycloneDDS xmlns="https://cdds.io/config">',
        '  <Domain id="any">',
        "    <General>",
        "      <Interfaces>",
        (f'        <NetworkInterface name="{GO2_IFACE_PLACEHOLDER}" priority="default" '
        'multicast="default" />'),
        "      </Interfaces>",
        "    </General>",
        "  </Domain>",
        "</CycloneDDS>",
        "XML",
    ]
    return Section(
        key="T9",
        title="Unitree overlay and CycloneDDS environment",
        purpose=(
            "CycloneDDS bound to the wrong NIC is *the* classic zero-topics failure, and "
            "at 09:00 it presents as 'the dog looks dead'. Without the `unitree_ros2` "
            "interface packages sourced, `ros2 bag record` cannot resolve the dog message "
            "types and every dog topic on the command line is skipped — 10.2% of the byte "
            "budget, silently. Neither failure raises an error. Both are configuration, "
            "and both are settled here before the recorder starts.\n\n"
            f"**`configs/robot.yaml:128` and `:342` carry `{STALE_INTERFACE_NAME}`. That is "
            "a placeholder from a different machine and it has never been observed on the "
            f"Orin. Do not type it.** The rows below carry `{GO2_IFACE_PLACEHOLDER}` / "
            f"`{L2_IFACE_PLACEHOLDER}`, which are deliberately unusable: a command still "
            "carrying one fails loudly instead of binding to the wrong interface."
        ),
        rows=(
            CommandRow(
                row_id="T9.1",
                title=f"HARD STOP — firmware pin ≥ {FIRMWARE_PIN} before ANY LAN join",
                command=(
                    "# Not a shell command. Read the firmware version in the Unitree app,",
                    "# phone only, with nothing else attached to the dog's network, and",
                    "# record it in the run header BEFORE a cable is connected.",
                    ("grep -n 'firmware' scrum/20260814/task_1/S2_STATUS.md "
                    "|| echo '(record the reading in the run sheet run header)'"),
                ),
                expected=(
                    f"A version string of the form `V1.1.x`, recorded, and **≥ {FIRMWARE_PIN}**. "
                    "Unitree DDS on the robot LAN is unauthenticated by design; pre-"
                    f"{FIRMWARE_PIN} firmware is treated as RCE-capable on home Wi-Fi."
                ),
                stop=(
                    f"Below {FIRMWARE_PIN}, or unreadable (unknown = absent, fail closed): "
                    "**STOP. Wake the owner.** Do not attach the Orin or the laptop to the "
                    "robot LAN. The session takes the DEGRADE-MMP path — mount, measure, "
                    "photograph, record nothing — which is a legitimate outcome. T9.2-T9.6 "
                    "and every dog topic in T10 are void until this clears; T7 and T8 touch "
                    "no robot network and remain valid."
                ),
                provenance=(
                    "[CITE] adr/0002-firmware-pin.md §1 (the pin) and "
                    "session/TONIGHT_CHECKLIST.md PRE-1 (how it is read and its branches)"
                ),
            ),
            CommandRow(
                row_id="T9.2",
                title="Discover the REAL interface names — never guess, never copy the config",
                command=(
                    "ip -brief addr",
                    "ip -o link show",
                    "ethtool <candidate> 2>/dev/null | grep -E 'Speed|Link detected'",
                ),
                expected=(
                    "Two names written down: the wired NIC for the Go2 LAN, and the second "
                    "NIC (or alias) for the L2. `ip -brief addr` is the only authority — "
                    "the interface name is a property of this Orin and nothing in the "
                    "repository knows it."
                ),
                stop=(
                    "No second Ethernet interface: STOP and take a recorded N6a branch "
                    "(USB-Ethernet adapter / IP alias / serial L2) before continuing. The "
                    "only candidate reporting `Link detected: no`: STOP — binding DDS to a "
                    "down interface is the zero-topics failure with an innocent-looking "
                    "config file."
                ),
                provenance="[CITE] session/TONIGHT_CHECKLIST.md N6a",
            ),
            CommandRow(
                row_id="T9.3",
                title="Render the CycloneDDS config, then substitute the real name",
                command=(
                    *xml_lines,
                    "",
                    "# Substitute the name T9.2 printed. The placeholder must be gone",
                    "# before the file is used by anything.",
                    (f'sed -i "s/{GO2_IFACE_PLACEHOLDER}/<the name ip -brief addr printed>/" '
                    "~/cyclonedds.xml"),
                    "cat ~/cyclonedds.xml",
                    f"grep -c '{GO2_IFACE_PLACEHOLDER}' ~/cyclonedds.xml",
                    "export CYCLONEDDS_URI=file://$HOME/cyclonedds.xml",
                ),
                expected=(
                    "`grep -c` prints **0**. The file names the interface `ip -brief addr` "
                    "printed, and `CYCLONEDDS_URI` is an absolute `file://` URI. The "
                    "`<Interfaces><NetworkInterface name=…>` schema is Cyclone 0.10+, which "
                    f"is what ROS 2 {distro.value} ships."
                ),
                stop=(
                    "`grep -c` prints anything but 0: **STOP.** The placeholder is still "
                    "there and CycloneDDS will refuse the config or fall back to a NIC "
                    "nobody chose. If H-1 reported an older distro whose Cyclone wants "
                    "`<NetworkInterfaceAddress>` instead, STOP — that is the branch that "
                    "voids this whole addendum."
                ),
                provenance=(
                    "[CITE] TONIGHT_CHECKLIST N6d · [UNVERIFIED-SYNTAX] on the Cyclone "
                    "schema for anything older than 0.10"
                ),
            ),
            CommandRow(
                row_id="T9.4",
                title="ROS_DOMAIN_ID unset, RMW consistent, in the shell that will record",
                command=(
                    ("env | grep -E 'ROS_DOMAIN_ID|RMW_IMPLEMENTATION|CYCLONEDDS_URI' "
                    "|| echo '(none set)'"),
                    ("grep -rn 'ROS_DOMAIN_ID' ~/.bashrc ~/.profile /etc/environment "
                    "2>/dev/null || echo '(no rc entries)'"),
                    "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp",
                ),
                expected=(
                    "`ROS_DOMAIN_ID` **unset** — i.e. domain 0, matching "
                    "`configs/robot.yaml:129 domain_id: 0`. `CYCLONEDDS_URI` set from T9.3. "
                    "`RMW_IMPLEMENTATION` identical in every terminal that will run a "
                    "driver or the recorder."
                ),
                stop=(
                    "`ROS_DOMAIN_ID` set anywhere, or two terminals disagreeing about the "
                    "RMW: STOP and make them consistent before launching anything. Two RMWs "
                    "in two terminals is another silent zero-topics failure, and it gets "
                    "diagnosed as a dead robot."
                ),
                provenance="[CITE] TONIGHT_CHECKLIST N6d · [REPO] configs/robot.yaml:129",
            ),
            CommandRow(
                row_id="T9.5",
                title="Prove the binding — including the negative control",
                command=(
                    "# terminal 1 — the intended NIC",
                    "sudo tcpdump -i <the Go2 NIC from T9.2> -n udp portrange 7400-7500",
                    "# terminal 2 — participant discovery only; this session emits no topic",
                    _source_ros(distro),
                    "export CYCLONEDDS_URI=file://$HOME/cyclonedds.xml",
                    "ros2 daemon stop; ros2 daemon start; ros2 node list",
                    "# terminal 1 again, on the OTHER interface",
                    "sudo tcpdump -i <the other NIC> -n udp portrange 7400-7500",
                ),
                expected=(
                    "Discovery traffic on the intended NIC, and **nothing on the other "
                    "one**. The negative control is what actually proves the binding; "
                    "traffic on the intended NIC alone proves only that something is "
                    "talking."
                ),
                stop=(
                    "Discovery on the wrong NIC, or on both: STOP. The config is not being "
                    "read — check the `file://` URI, that the path is absolute, and that "
                    "the export survives into the shell that will run the recorder. Fix it "
                    "now; at 09:00 this presents as `ros2 topic list` empty and the dog "
                    "apparently dead."
                ),
                provenance=(
                    "[CITE] TONIGHT_CHECKLIST N6d, with one deliberate divergence: N6d "
                    "generates traffic by publishing a test topic. This session is "
                    "sensors-only, so the row uses participant discovery from `ros2 node "
                    "list` instead — same evidence, nothing emitted onto the robot's topics."
                ),
            ),
            CommandRow(
                row_id="T9.6",
                title="Source the unitree_ros2 interface overlay and prove the types resolve",
                command=(
                    _source_ros(distro),
                    "source ~/unitree_ros2/cyclonedds_ws/install/setup.bash",
                    "ros2 interface list | grep -iE 'unitree' | head -20",
                    "ros2 interface show unitree_go/msg/LowState | head -30",
                ),
                expected=(
                    "The `unitree_go` / `unitree_api` interfaces resolve. `LowState` shows "
                    "`imu_state`, `motor_state`, `bms_state`, `foot_force`, "
                    "`foot_force_est`, `tick`, `wireless_remote`, `power_v`, `power_a` — "
                    "and **no timestamp field**, which is the channel matrix's whole point. "
                    "These are message-definition packages only: nothing here creates a "
                    "command surface, a lease or a motion client."
                ),
                stop=(
                    "Interfaces absent: **STOP. Owner decision.** With no `unitree_go` "
                    "interfaces the recorder resolves no dog message type and records **no "
                    "dog topic at all** — the bag simply has none, with no error. The "
                    "fallback is a second artifact in a format no downstream tool reads. "
                    "Write the acceptance down before recording, not after."
                ),
                provenance="[CITE] session/TONIGHT_CHECKLIST.md N6f",
            ),
        ),
    )


def _t10_section(distro: RosDistro, output_dir: Path, storage_config_path: Path) -> Section:
    plan = plan_for_session(
        output_dir, storage_config_path=storage_config_path, distro=distro
    )
    argv = record_command(plan)
    help_cmd = " ".join(record_help_command())
    topic_cmd = " ".join(preflight_topic_check_command())
    infos = camera_info_topics()
    transforms = transform_topics()
    gate_rows = "\n".join(
        f"    - `{module}.{symbol}` — {why}" for module, symbol, why in GATE_REFERENCES
    )
    return Section(
        key="T10",
        title="The recorder: argv, storage config, and the stop gates around it",
        purpose=(
            "This is the only row on the sheet that writes the session. Every flag in the "
            f"argv is rendered by `Rosbag2Plan(distro={distro.value!r})` and cleared against "
            "the installed recorder's own `--help` first, because the historical sheets "
            "hard-code flags Humble's recorder does not have — argparse exits 2 and the "
            "session records zero bytes. The gates on either side are S-1's, named by "
            "their real symbols."
        ),
        rows=(
            CommandRow(
                row_id="T10.1",
                title="Clear the argv against the INSTALLED recorder — MANDATORY, first",
                command=(
                    _source_ros(distro),
                    f"{help_cmd} > {RECORD_HELP_PATH}",
                    "cd <the Parcel checkout on the Orin>",
                    (f"python3 -m scripts.parcel_capture.rosbag2 --distro {distro.value} "
                    f"--verify-help {RECORD_HELP_PATH}"),
                    'echo "verify-help exit=$?"',
                ),
                expected=(
                    "`argv cleared against …: N flag(s) all present` and **exit 0**. The "
                    "checker also refuses a help text it does not recognise: an "
                    "unrecognised help must never read as 'nothing wrong'."
                ),
                stop=(
                    "Exit 2 (`refused:`): **STOP.** The installed recorder lacks a flag this "
                    "argv uses. Regenerate this sheet for the distro the machine actually "
                    "runs — one command: `python -m scripts.parcel_capture.stage0_addendum "
                    "--distro <observed> --emit-distro`. Do NOT edit the command line by "
                    "hand; that is the second handwritten CLI working agreement 7 forbids. "
                    "Exit 3: `ros2` is not on PATH in this shell — source the overlay and "
                    "repeat."
                ),
                provenance=_recorder_provenance(distro),
            ),
            CommandRow(
                row_id="T10.2",
                title="Emit the storage config OUTSIDE the bag directory, before the argv uses it",
                command=(
                    f"mkdir -p {storage_config_path.parent}",
                    ("python3 -m scripts.parcel_capture.rosbag2 "
                    f"--emit-storage-config {storage_config_path}"),
                    f"cat {storage_config_path}",
                ),
                expected=(
                    f"`wrote {storage_config_path}` and a file containing "
                    '`compression: "None"` and `compressionLevel: "Default"` — never the '
                    "empty string, which makes the MCAP storage plugin fail its YAML "
                    "conversion so `ros2 bag record` exits 1 having written zero bytes. "
                    f"Note the path is **not** under `{output_dir}`: creating anything "
                    "inside the record target makes that directory exist, and the recorder "
                    "refuses an output folder that already exists."
                ),
                stop=(
                    "File not written, or the directory is not on the record target: STOP. "
                    "On Humble `--storage-config-file` is argparse's `FileType('r')`, so a "
                    "missing file is an exit-2 before any recording starts. If the "
                    "installed plugin later rejects the file, the documented remedy is to "
                    "drop `--storage-config-file` and re-run: the plugin default measured "
                    "as chunked-and-uncompressed, which the stdlib reader counts. You lose "
                    "the crash-safety tuning, not the session."
                ),
                provenance=(
                    "[MEASURED] enum spellings against rosbag2_storage_mcap 0.26.11 + "
                    "libmcap 1.3.1 (PS-M F2) · [MEASURED-JAZZY-SANDBOX] the output-folder "
                    "rule in ros2bag/verb/record.py:273-274"
                ),
            ),
            CommandRow(
                row_id="T10.3",
                title="STOP GATE — support-artifact reconciliation against the observed graph",
                command=(
                    _source_ros(distro),
                    f"{topic_cmd} > {TOPIC_LIST_PATH}",
                    "python3 - <<'PY'",
                    "from pathlib import Path",
                    ("from scripts.parcel_capture.preflight import "
                    "reconcile_support_topics_or_raise"),
                    f"text = Path({TOPIC_LIST_PATH!r}).read_text()",
                    "print(reconcile_support_topics_or_raise(text).to_dict())",
                    "PY",
                ),
                expected=(
                    f"No refusal, and every one of the {len(infos)} `camera_info` topics "
                    f"plus {len(transforms)} transform topic(s) reported `present` with the "
                    "declared type. Unknown is absent; a type mismatch is affirmative "
                    "evidence of misconfiguration and refuses regardless of need."
                ),
                stop=(
                    "`PreflightError: support-artifact reconciliation refused`: **STOP — do "
                    "not start the recorder.** A REQUIRED support topic missing at run time "
                    "means the bag it would have completed cannot certify, and no "
                    "post-session effort recovers intrinsics that were never recorded. Fix "
                    "the driver launch (T7.3/T7.4) and repeat this row."
                ),
                provenance=(
                    "[DERIVED] gate name cross-checked against S-1's landed API · "
                    "[MEASURED-JAZZY-SANDBOX] `ros2 topic list -t` accepts `-t`"
                ),
            ),
            CommandRow(
                row_id="T10.4",
                title="STOP GATE — snapshot the transient-local /tf_static BEFORE record start",
                command=(
                    _source_ros(distro),
                    ("timeout 15 ros2 topic echo /tf_static --once "
                    "--qos-durability transient_local --qos-reliability reliable "
                    "> /tmp/parcel_tf_static.yaml"),
                    "wc -l /tmp/parcel_tf_static.yaml",
                ),
                expected=(
                    "A non-empty capture of the latched transforms. `/tf_static` is "
                    "published once and latched, so a recorder started afterwards may never "
                    "receive it; the snapshot is bound into the sidecar under schema "
                    f"`{STATIC_TF_SNAPSHOT_SCHEMA_NAME}` and validated, not trusted."
                ),
                stop=(
                    "Empty capture, or no `/tf_static` on the graph: **STOP.** A graph with "
                    "no `/tf_static` has nothing to snapshot either, and the GO-RECORD gate "
                    "refuses a bag whose optical frames have no parent. Prose is not a "
                    "snapshot: a hand-written description of the mount is geometry with "
                    "uncertainty (working agreement 6), never calibrated TF, and it cannot "
                    "satisfy this gate."
                ),
                provenance=(
                    "[DERIVED] schema name cross-checked against S-1's sidecar · "
                    "[MEASURED-JAZZY-SANDBOX] `ros2 topic echo` accepts `--once`, "
                    "`--qos-durability`, `--qos-reliability`"
                ),
            ),
            CommandRow(
                row_id="T10.5",
                title="Confirm the recording shell, and that the output folder does NOT exist",
                command=(
                    _source_ros(distro),
                    "source ~/unitree_ros2/cyclonedds_ws/install/setup.bash",
                    "source ~/unilidar_sdk2/unitree_lidar_ros2/install/setup.bash",
                    "export CYCLONEDDS_URI=file://$HOME/cyclonedds.xml",
                    "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp",
                    (f"test ! -d {output_dir} && echo 'output folder absent: OK' "
                    "|| echo 'OUTPUT FOLDER EXISTS — STOP'"),
                    f"df -h {output_dir.parent}",
                ),
                expected=(
                    "`output folder absent: OK`, all three overlays sourced in **this** "
                    "shell, and free space on the record target at or above the run-specific "
                    "figure in `DISK_LEDGER.md` for the take length you intend."
                ),
                stop=(
                    "`OUTPUT FOLDER EXISTS`: **STOP and choose a new take directory.** The "
                    "recorder checks `os.path.isdir(uri)` and exits with `Output folder … "
                    "already exists` before writing anything — a re-run after an aborted "
                    "take fails here, not mysteriously later. Overlays missing from this "
                    "shell: STOP and return to T9.6 — a recorder launched from an unsourced "
                    "shell records a bag with no dog topics and no error."
                ),
                provenance=(
                    "[MEASURED-JAZZY-SANDBOX] ros2bag/verb/record.py:273-274 — "
                    "`if os.path.isdir(uri): return print_error(...)`, executed: "
                    "`[ERROR] [ros2bag]: Output folder '…' already exists.` exit 1"
                ),
            ),
            CommandRow(
                row_id="T10.6",
                title="THE RECORD COMMAND — rendered from the plan, never typed from memory",
                command=(" ".join(argv),),
                argv_markers=True,
                expected=(
                    f"The recorder starts and creates `{output_dir}/` containing "
                    "`metadata.yaml` and exactly ONE `.mcap` file that grows. "
                    f"{len(plan.topics)} topics are subscribed. `--max-bag-size 0` and "
                    "`--max-bag-duration 0` are emitted explicitly and mean *never split*: "
                    "more than one `.mcap`, or a `write_split` count above 0, is the take "
                    "script's abort condition."
                ),
                stop=(
                    "Exit 2 before any file appears — an unrecognised option: **STOP**, "
                    "return to T10.1, and regenerate this sheet for the distro that machine "
                    "actually runs. Exit 1 with zero bytes — the storage config was "
                    "rejected: **STOP**, apply T10.2's documented remedy and restart the "
                    "take. A second `.mcap` appearing mid-take: **STOP** the take per the "
                    "abort rule and record why."
                ),
                provenance=_recorder_provenance(distro),
            ),
            CommandRow(
                row_id="T10.7",
                title="STOP GATES after the take — calibration, transforms, sync, certification",
                command=(
                    "cd <the Parcel checkout on the Orin>",
                    "python3 - <<'PY'",
                    "from scripts.parcel_capture.sidecar import finalize_rosbag2",
                    f"sidecar, path = finalize_rosbag2({str(output_dir)!r}, bag_id='<run id>',",
                    "                                 require_go_record=True)",
                    "print(path, sidecar['capture']['go_record']['status'])",
                    "PY",
                ),
                expected=(
                    "`GO-RECORD` and a sidecar written beside the bag. The gates that had "
                    "to pass, by name:\n\n" + gate_rows
                ),
                stop=(
                    "`GoRecordRefusedError`: **STOP and read the refusal list — it names "
                    "every reason.** Nothing is written: a certified manifest for an "
                    "uncertifiable bag must not exist on disk even transiently. A refusal "
                    "here is not a tooling problem; it is the dataset saying it cannot feed "
                    "camera SLAM or camera-LiDAR fusion. Record the refusals verbatim, then "
                    "decide whether the take is repeatable while the rig is still "
                    "assembled — after the bracket comes off, it is not."
                ),
                provenance=(
                    "[DERIVED] every symbol named here is cross-checked against S-1's live "
                    "modules by tests/test_stage0_addendum.py"
                ),
            ),
        ),
        appendix=(
            "### The `--storage-config-file` bytes",
            "",
            (f"Written to `{storage_config_path}` by T10.2. Reproduced here so the sheet "
            "is self-contained if the Orin has no checkout yet; the bytes are "
            "`rosbag2.storage_config_yaml()` and nothing else."),
            "",
            _storage_block(),
            "",
        ),
    )


def build_addendum(
    distro: RosDistro | str = RosDistro.HUMBLE,
    *,
    output_dir: Path = S2_OUTPUT_DIR,
    storage_config_path: Path = S2_STORAGE_CONFIG_PATH,
) -> Addendum:
    """The four sections for one distro, validated at construction."""

    resolved = parse_distro(distro)
    return Addendum(
        distro=resolved,
        output_dir=Path(output_dir),
        storage_config_path=Path(storage_config_path),
        sections=(
            _t7_section(resolved),
            _t8_section(resolved),
            _t9_section(resolved),
            _t10_section(resolved, Path(output_dir), Path(storage_config_path)),
        ),
    )


def _first_sentence(text: str, limit: int = 96) -> str:
    flat = " ".join(text.replace("\n", " ").split())
    cut = flat.find(". ")
    if cut != -1:
        flat = flat[: cut + 1]
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return flat


def _render_row(row: CommandRow, distro: RosDistro) -> list[str]:
    out = [f"#### {row.row_id} · {row.title}", ""]
    out.append(f"**Provenance.** {row.provenance}")
    out.append("")
    if row.argv_markers:
        # No language tag inside the marked block: extract_argv_from_addendum()
        # requires exactly one line between the fences, and a ```bash tag is a
        # second one. The fence is bare here and only here.
        out.append(ARGV_BEGIN.format(distro=distro.value))
        out.append("```")
        out.extend(row.command)
        out.append("```")
        out.append(ARGV_END.format(distro=distro.value))
    else:
        out.append("```bash")
        out.extend(row.command)
        out.append("```")
    out.append("")
    out.append(f"**EXPECTED.** {row.expected}")
    out.append("")
    out.append(f"**STOP.** {row.stop}")
    out.append("")
    return out


def render_addendum(
    distro: RosDistro | str = RosDistro.HUMBLE,
    *,
    output_dir: Path = S2_OUTPUT_DIR,
    storage_config_path: Path = S2_STORAGE_CONFIG_PATH,
) -> str:
    """The per-distro operator sheet, byte-stable.

    No timestamps, no host lookups, no probes: two calls in the same tree
    produce identical bytes, which is what lets
    ``tests/test_stage0_addendum.py`` compare the committed file against this
    function instead of trusting a human to have re-run the generator.
    """

    addendum = build_addendum(
        distro, output_dir=output_dir, storage_config_path=storage_config_path
    )
    resolved = addendum.distro
    other = RosDistro.JAZZY if resolved is RosDistro.HUMBLE else RosDistro.HUMBLE
    plan = plan_for_session(
        addendum.output_dir,
        storage_config_path=addendum.storage_config_path,
        distro=resolved,
    )

    out: list[str] = []
    w = out.append
    w(f"# Stage-0 command addendum — ROS 2 {resolved.value.upper()} sheet (card S-2)")
    w("")
    w("> # ⚠ DRAFT UNTIL H-1 — NOT YET OPERATIVE")
    w(">")
    w(
        "> Nobody has executed a command on the Orin. Its ROS distro is an "
        "**assertion, not an observation**. Two sheets are generated: this one for "
        f"ROS 2 **{resolved.value}**, and one for ROS 2 **{other.value}**."
    )
    w(">")
    w(
        "> **Exactly one becomes operative** when the operator reports the observed "
        "distro from the H-1 identity dump (`cat /etc/nv_tegra_release; lsb_release "
        f"-a; ls /opt/ros`). If H-1 reports `/opt/ros/{resolved.value}`, this document "
        f"is the sheet and `{Path(DOCUMENT_RELPATHS[other]).name}` is **VOID**. If it "
        f"reports `/opt/ros/{other.value}`, **this document is VOID** and "
        f"`{Path(DOCUMENT_RELPATHS[other]).name}` is the sheet."
    )
    w(">")
    w(
        "> If H-1 reports **anything else** — Foxy, JetPack 5.x, no ROS at all — "
        "**both are void.** Take REVISED_BOARD.md H-1's 'anything else' branch: STOP, "
        "report the exact output, and retarget. The generator refuses to render an "
        "unknown distro rather than defaulting to a plausible one."
    )
    w(">")
    w("> Regeneration after H-1 is one command:")
    w(">")
    w("> ```")
    w(
        "> .parcel/bin/python -m scripts.parcel_capture.stage0_addendum "
        f"--distro {resolved.value} --emit-distro"
    )
    w("> ```")
    w("")
    w("> ## ⚠ GENERATED FILE — do not hand-edit")
    w(">")
    w(
        "> Every command below is rendered by "
        "`scripts/parcel_capture/stage0_addendum.py::render_addendum()`. The recorder "
        "argv comes from `Rosbag2Plan(distro=…)`; the RealSense launch arguments and "
        "every topic name are DERIVED from `rosbag2.RECORDED_TOPICS` / "
        "`rosbag2.SUPPORT_TOPICS`; the camera profile is `budget.RECOMMENDED_PROFILE`. "
        "Hand-editing is a defect: `tests/test_stage0_addendum.py` reddens until it is "
        "reverted."
    )
    w("")
    w("## 0 · What this is, and what it replaces")
    w("")
    w(
        "`scrum/20260814/task_1/README.md`'s opening assessment: *\"Stage-0 command "
        "transcription has no first-class rows for the RealSense launch, L2 launch, "
        "Unitree overlay and actual `ros2 bag record` command.\"* Those four rows are "
        "**T7-T10**, and they are below. This document is **run-specific** and lives "
        f"under this task; `{HISTORICAL_RUN_SHEET}` and `{HISTORICAL_CHECKLIST}` are "
        "historical provenance and are not edited (working agreement 3)."
    )
    w("")
    w(
        "Working agreement 7 is why this is generated: *operator commands are rendered "
        "from the distro-aware plan after `--verify-help`; they are not maintained as a "
        "second handwritten CLI in Markdown.* The historical sheets hard-code "
        "`--disable-keyboard-controls`, which Humble's recorder does not declare — "
        "argparse exits 2 and the session records zero bytes. That flag cannot reach "
        "this document: every rendered `ros2 bag record` line is checked against this "
        "distro's own recorder CLI at construction time, and an unsupported flag is a "
        "refusal before a byte of Markdown exists."
    )
    w("")
    w("### Run parameters")
    w("")
    w("| | |")
    w("|---|---|")
    w(f"| ROS 2 distro (DRAFT — H-1 confirms) | `{resolved.value}` |")
    w(f"| Record target | `{addendum.output_dir}` |")
    w(f"| Storage config (outside the record target) | `{addendum.storage_config_path}` |")
    w(f"| Writer profile | `{plan.profile.value}` (chunking off) |")
    w(
        f"| Camera profile | `{RECOMMENDED_PROFILE.label}` "
        "(colour + depth + infra1 + infra2 + IMU) |"
    )
    w(f"| Topics on the record command line | {len(plan.topics)} |")
    w(
        f"| of which S-1 support artifacts | {len(camera_info_topics())} `camera_info` "
        f"+ {len(transform_topics())} transform |"
    )
    w("")
    w("### Row index")
    w("")
    w("| row | what it does | passes when |")
    w("|---|---|---|")
    for section in addendum.sections:
        for row in section.rows:
            w(f"| `{row.row_id}` | {row.title} | {_first_sentence(row.expected)} |")
    w("")
    w(
        "Every row carries an exact command, an expected observable, and an explicit "
        "STOP branch. A row missing any of the three cannot be constructed — the "
        "generator refuses."
    )
    w("")

    for section in addendum.sections:
        w("---")
        w("")
        w(f"## {section.key} · {section.title}")
        w("")
        w(section.purpose)
        w("")
        for row in section.rows:
            out.extend(_render_row(row, resolved))
        if section.appendix:
            out.extend(section.appendix)

    w("---")
    w("")
    w("## What this sheet does not prove")
    w("")
    w(
        "1. **No command in this document has ever executed on a real Orin.** Not one. "
        "The distro is unread, the drivers are uninstalled, and no topic here has been "
        "observed. H-1 (identity) and H-2 (the no-dog rehearsal) are the cards that "
        "produce that evidence; this sheet is what H-2 executes, not a substitute for "
        "having executed it."
    )
    w(
        "2. **The RealSense and L2 launch argument spellings are UNVERIFIED.** They "
        "differ across driver and SDK revisions, which is why `--show-args` (T7.2) and "
        "the SDK's own README (T8.2) are mandatory rows that precede the launches "
        "rather than footnotes after them."
    )
    w(
        "3. **Every topic name here is documentation-derived.** `ros2 topic list -t` on "
        "the real graph is the authority, and a name that differs is a finding to "
        "record, not an error to work around."
    )
    w(
        f"4. **The {resolved.value} recorder CLI facts are "
        + (
            "measured against a Jazzy sandbox, not against the Orin"
            if resolved is RosDistro.JAZZY
            else "read from ros2/rosbag2's source, not executed on Humble by anyone"
        )
        + ".** T10.1 exists precisely because that gap cannot be closed from a desk."
    )
    w(
        "5. **The gate names are cross-checked; the gate behaviour is not.** A test "
        "asserts every symbol named in T10.7 exists in S-1's modules. Whether those "
        "gates refuse the right bags is S-1's evidence, not this card's."
    )
    w(
        "6. **Nothing here authorises motion.** Every row observes, launches a vendor "
        "sensor driver, or records. No Parcel process commands the robot, and the "
        "generator refuses to render a row that would."
    )
    w("")
    return "\n".join(out) + "\n"


def emit_per_distro_addendum(
    distro: RosDistro | str, path: Path | None = None
) -> Path:
    """Write one per-distro sheet. ``distro`` is required — never guessed."""

    resolved = parse_distro(distro)
    target = document_path(resolved) if path is None else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_addendum(resolved), encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.parcel_capture.stage0_addendum",
        description=(
            "Render the run-specific Stage-0 T7–T10 command addendum. T10 argv "
            "comes only from Rosbag2Plan/record_command. FINALIZE is blocked "
            "until H-1 reports the Orin distro."
        ),
    )
    parser.add_argument(
        "--emit",
        action="store_true",
        help=f"write the combined INDEX (no command rows) to {ADDENDUM_RELATIVE}",
    )
    parser.add_argument(
        "--print-argv",
        choices=[item.value for item in RosDistro],
        default=None,
        help="print one distro's T10 argv (from record_command) and exit",
    )
    parser.add_argument(
        "--verify-help",
        metavar="PATH",
        default=None,
        help="saved `ros2 bag record --help`; requires --print-argv's distro "
        "via --distro",
    )
    parser.add_argument(
        "--distro",
        default=RosDistro.HUMBLE.value,
        help=(
            "ROS 2 distro of the machine that will type these commands "
            "(humble|jazzy). Free-form on purpose: an unknown value is refused by "
            "parse_distro() with the H-1 'anything else' branch spelled out, not by "
            "an argparse choices message that says nothing about what to do next."
        ),
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="write the PER-DISTRO sheet for --distro here ('-' means stdout)",
    )
    parser.add_argument(
        "--emit-distro",
        action="store_true",
        help=(
            "write the per-distro sheet for --distro to its committed path "
            "(scrum/20260814/task_1/STAGE0_ADDENDUM_<DISTRO>.md)"
        ),
    )
    parser.add_argument(
        "--emit-all-distros",
        action="store_true",
        help="write BOTH per-distro sheets to their committed paths",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selected = parse_distro(args.distro)
    except AddendumRefusedError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    if args.emit_all_distros:
        for item in RosDistro:
            print(f"wrote {emit_per_distro_addendum(item)}")
        return 0
    if args.emit_distro:
        print(f"wrote {emit_per_distro_addendum(selected)}")
        return 0
    if args.out is not None:
        if args.out == "-":
            sys.stdout.write(render_addendum(selected))
        else:
            print(f"wrote {emit_per_distro_addendum(selected, Path(args.out))}")
        return 0
    if args.emit:
        # The path is explicit at the call site on purpose: emit_addendum() has
        # no default target, so nothing but a deliberate CLI invocation (or a
        # test passing tmp_path) can write into the repo tree.
        target = emit_addendum(addendum_path())
        print(f"wrote {target}")
        return 0
    if args.print_argv:
        distro = RosDistro(args.print_argv)
        cmd = rendered_argv(distro)
        if distro is RosDistro.HUMBLE:
            try:
                refuse_if_humble_carries_disable_keyboard(cmd)
            except Rosbag2RefusedError as error:
                print(f"refused: {error}", file=sys.stderr)
                return 2
        print(" ".join(cmd))
        return 0
    if args.verify_help:
        distro = selected
        try:
            help_text = Path(args.verify_help).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError as error:
            print(f"unavailable: cannot read {args.verify_help}: {error}", file=sys.stderr)
            return 3
        try:
            checked = clear_argv_against_help(
                rendered_argv(distro), help_text, distro=distro
            )
        except Rosbag2RefusedError as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
        print(
            f"argv cleared against {args.verify_help} "
            f"(distro={distro.value}): {len(checked)} flag(s) all present"
        )
        return 0
    print(render_combined_index())
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
