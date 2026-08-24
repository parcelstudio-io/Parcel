"""``parcel-unitree-control`` — the commissioning-only operator tool (card W0-B).

Before this card, this CLI built its manager with
``build_unitree_sport_control_manager``, which refuses to construct anything
until ``enable_lease`` / ``axes_commissioned`` / ``state_frame_commissioned`` /
``allowed_modes`` are already true in configuration. Those four facts are what
commissioning exists to establish, so the tool could not bootstrap without first
asserting its own conclusion. It now drives
``parcel_robot.commissioning`` through
``build_unitree_sport_commissioning_session`` instead, and works while all four
flags are false.

Four subcommands, in the order an operator uses them:

``observe``
    Read-only. Subscribes to feedback, claims no lease, constructs no
    controller, and prints what the state stream looks like with nothing
    commanded — including the modes the next step must be armed with.
``run``
    The armed part. Requires ``--arm``, an operator, a robot serial, every
    safety acknowledgement, and the observed modes. Commands one axis at a
    time, inside 0.02-0.05 m/s, for at most one stop budget, then stops and
    waits for feedback to confirm the stop. Writes an fsync'd journal and a
    ``CommissioningRecordV1``.
``review``
    A second person — not the operator — accepts or rejects a record. The
    attestation is bound to the record's content digest.
``apply``
    Prints the ``control:`` configuration a *reviewed, passing* record
    authorizes. It refuses everything else, and it prints rather than writes:
    a human puts the flags in the config file, deliberately.

Nothing here can move a robot without ``--arm`` plus every acknowledgement, and
nothing here can reach ``RobotRuntime``.
"""

from __future__ import annotations

import argparse
import json
import math  # ---- CARD HW-2 (task_40): the --duration finiteness check ----
import sys
import time  # ---- CARD HW-2 (task_40): the observe --duration clock ----
from datetime import datetime, timezone
from pathlib import Path

from parcel_robot import __version__
from parcel_robot.commissioning.limits import (
    DEFAULT_MAX_DURATION_S,
    MAX_LINEAR_MPS,
    MAX_YAW_RAD_S,
    MIN_LINEAR_MPS,
    MIN_YAW_RAD_S,
    OPERATOR_INSTRUCTIONS,
    REQUIRED_ACKNOWLEDGEMENTS,
    CommissioningArming,
    CommissioningAxis,
    CommissioningError,
)
from parcel_robot.commissioning.record import (
    CommissioningRecordV1,
    CommissioningReviewError,
    ObservationEvidence,
    ObservedDirection,
    commissioned_control_config,
)
from parcel_robot.config import ConfigStore
from parcel_robot.control.factory import (
    build_unitree_sport_commissioning_session,
    build_unitree_sport_observer,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "robot.yaml"
FALLBACK_CONFIG = Path(__file__).with_name("config") / "robot.yaml"

#: Mid-band defaults, derived from the band rather than chosen: the middle of
#: the commissioning band is the least surprising place to start, and the cap
#: is the longest step the band allows.
DEFAULT_LINEAR_SPEED_MPS = (MIN_LINEAR_MPS + MAX_LINEAR_MPS) / 2.0
DEFAULT_YAW_SPEED_RAD_S = (MIN_YAW_RAD_S + MAX_YAW_RAD_S) / 2.0
DEFAULT_DURATION_S = DEFAULT_MAX_DURATION_S

_DIRECTIONS = tuple(direction.value for direction in ObservedDirection)


def main(argv: list[str] | None = None) -> int:
    """Run one commissioning subcommand. Returns the process exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "observe": _run_observe,
        "run": _run_session,
        "review": _run_review,
        "apply": _run_apply,
    }
    return handlers[args.command](args, parser)


# --------------------------------------------------------------------- observe


def _run_observe(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    del parser
    store = ConfigStore(args.config)
    observer = build_unitree_sport_observer(store.section("control"))
    _echo("Read-only observation. No lease is claimed and no controller exists.")
    # ---- CARD HW-2 go2-backend (scrum/20260822/task_40): --duration ---------
    #
    # HANDOFF HO-6, from HW-8's box-day runbook: step S19 wants the operator to
    # WATCH the state stream for a while ("ten runs"), and `observe` had no way
    # to say that -- it returns the moment it has `--min-samples` distinct
    # samples, so a longer look meant running the command ten times by hand.
    #
    # It is a LOOP OVER THE EXISTING WINDOW, not a new observation mode, and
    # deliberately so: `CommissioningObserver.observe` (commissioning/session.py
    # :293) is not this card's to edit, and its refusals -- not stationary,
    # vendor fault, too few samples -- are exactly the ones an operator needs
    # to keep. So `--min-samples`/`--timeout` keep their meanings per window,
    # each window is a real `ObservationEvidence`, and a refusal in ANY window
    # ends the command rc=1 the way one window always did.
    #
    # With `--duration` absent (the default) the loop runs once and every byte
    # of this subcommand's behaviour is what it was before this card.
    windows = []
    deadline = None if args.duration is None else time.monotonic() + float(args.duration)
    try:
        observer.start()
        while True:
            windows.append(observer.observe(min_samples=args.min_samples, timeout_s=args.timeout))
            if deadline is None or time.monotonic() >= deadline:
                break
    except CommissioningError as error:
        _echo(f"observation refused: {error}")
        return 1
    finally:
        observer.close()
    evidence = windows[-1]
    # ---- END CARD HW-2 ------------------------------------------------------
    _echo(json.dumps(evidence.as_dict(), indent=2, sort_keys=True))
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(evidence.as_dict(), indent=2, sort_keys=True) + "\n")
        _echo(f"observation written to {target}; pass it to `run --observation {target}`")
    # ---- CARD HW-2 (task_40): what a multi-window look actually measured ----
    # Sample counts are NOT summed: each window de-duplicates by sequence
    # within itself, so adding them across windows would double-count a stream
    # that went quiet. The three numbers that DO compose are reported instead,
    # and `--out` still writes ONE window's evidence in the shape
    # `run --observation` reads -- the last one, named as such.
    if args.duration is not None:
        _echo(
            json.dumps(
                {
                    "duration_summary": {
                        "requested_duration_s": float(args.duration),
                        "windows": len(windows),
                        "wall_clock_s": round(sum(w.duration_s for w in windows), 4),
                        "worst_max_interval_s": max(w.max_interval_s for w in windows),
                        "max_linear_speed_mps": max(w.max_linear_speed_mps for w in windows),
                        "max_yaw_speed_rad_s": max(w.max_yaw_speed_rad_s for w in windows),
                        "modes_seen": sorted({m for w in windows for m in w.modes_seen}),
                        "error_codes_seen": sorted(
                            {c for w in windows for c in w.error_codes_seen}
                        ),
                        "note": (
                            "per-window sample counts are not summed; the JSON above is "
                            "the LAST window, which is also what --out writes"
                        ),
                    }
                },
                indent=2,
                sort_keys=True,
            )
        )
    # ---- END CARD HW-2 ------------------------------------------------------
    _echo(
        "Arm the next phase with these modes: --mode "
        + " --mode ".join(str(mode) for mode in evidence.modes_seen)
    )
    return 0


# ------------------------------------------------------------------------- run


def _run_session(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.arm:
        parser.error("--arm is required; this subcommand can move physical hardware")
    missing = REQUIRED_ACKNOWLEDGEMENTS - set(args.ack)
    if missing:
        parser.error(
            "missing acknowledgement(s): "
            + ", ".join(sorted(missing))
            + " (see the printed operator instructions)"
        )
    if not args.mode:
        parser.error("--mode is required; run the observe subcommand first")
    directions = _parse_directions(args.observed_direction, parser)
    observation = _load_observation(args.observation, parser)
    if observation is not None and not set(args.mode) <= set(observation.modes_seen):
        parser.error(
            f"--mode {sorted(set(args.mode))} is not a subset of the modes the observation "
            f"actually saw {sorted(observation.modes_seen)}"
        )

    for index, line in enumerate(OPERATOR_INSTRUCTIONS, start=1):
        _echo(f"{index}. {line}")
    _echo("")

    store = ConfigStore(args.config)
    arming = CommissioningArming.arm(
        operator=args.operator,
        robot_serial=args.robot_serial,
        acknowledgements=args.ack,
        observed_modes=args.mode,
    )
    try:
        session = build_unitree_sport_commissioning_session(
            store.section("control"),
            store.safety_limits(),
            arming=arming,
            journal_path=args.journal,
        )
    except CommissioningError as error:
        _echo(f"commissioning refused: {error}")
        return 1

    axes = (
        tuple(CommissioningAxis(name) for name in args.axis)
        if args.axis
        else tuple(CommissioningAxis)
    )
    if observation is not None:
        session.adopt_observation(observation)
    failed = False
    try:
        session.start()
        for axis in axes:
            speed = args.yaw_speed if axis.is_angular else args.speed
            _echo(f"Commanding {axis.value} at {speed:g} for {args.duration:g}s. Watch the robot.")
            session.run_axis_step(
                axis,
                speed,
                args.duration,
                observed_direction=directions.get(axis, ObservedDirection.UNCERTAIN),
            )
            _echo(f"{axis.value}: step complete and stop confirmed.")
    except KeyboardInterrupt:
        failed = True
        _echo("Interrupted. The session is latched; use the physical E-stop if the robot moved.")
    except CommissioningError as error:
        failed = True
        _echo(f"commissioning stopped: {error}")
    finally:
        record = session.record(
            performed_at=_utc_now(),
            software_revision=args.software_revision,
            artifact_paths=args.artifact,
        )
        path = record.save(args.record_out)
        _echo(f"record written to {path} (outcome={record.outcome.value})")
        missing_evidence = record.missing_evidence()
        if missing_evidence:
            _echo("this record authorizes nothing; missing: " + ", ".join(missing_evidence))
    return 1 if failed or session.latched else 0


# ---------------------------------------------------------------------- review


def _run_review(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    record = CommissioningRecordV1.load(args.record)
    if args.reviewer.strip().casefold() == record.operator.strip().casefold():
        # The record refuses this too; the CLI says so before writing anything.
        parser.error(
            "a commissioning record must be reviewed by someone other than its operator "
            f"({record.operator!r})"
        )
    reviewed = record.reviewed_by(
        reviewer=args.reviewer,
        reviewed_at=_utc_now(),
        accepted=args.accept,
        notes=args.notes,
    )
    path = reviewed.save(args.out or args.record)
    _echo(f"review written to {path} (accepted={args.accept})")
    if not reviewed.authorizes_configuration():
        _echo(
            "this record still authorizes nothing; missing: "
            + ", ".join(reviewed.missing_evidence())
        )
        return 1
    return 0


# ----------------------------------------------------------------------- apply


def _run_apply(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    del parser
    record = CommissioningRecordV1.load(args.record)
    store = ConfigStore(args.config)
    try:
        updated = commissioned_control_config(store.section("control"), record)
    except CommissioningReviewError as error:
        _echo(f"refused: {error}")
        return 1
    _echo("Paste this into the control section of your robot config, then re-read it:")
    _echo(json.dumps({"control": {"unitree_sport": updated["unitree_sport"]}}, indent=2))
    return 0


# --------------------------------------------------------------------- plumbing


# ---- CARD HW-2 (task_40) ----
def _positive_seconds(value: str) -> float:
    """A duration argparse can refuse at parse time, with the reason."""

    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise argparse.ArgumentTypeError(
            f"a duration must be a positive, finite number of seconds; got {value!r}"
        )
    return seconds


# ---- END CARD HW-2 ----


def _build_parser() -> argparse.ArgumentParser:
    default_config = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else FALLBACK_CONFIG
    parser = argparse.ArgumentParser(
        description="Commission Parcel's feedback-supervised Unitree Sport controller"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    observe = subparsers.add_parser("observe", help="read-only feedback phase (claims no lease)")
    observe.add_argument("--config", default=str(default_config))
    observe.add_argument("--min-samples", type=int, default=20)
    observe.add_argument("--timeout", type=float, default=5.0)
    observe.add_argument(
        "--out",
        default=None,
        help="write the observation evidence here so `run --observation` can carry it",
    )
    # ---- CARD HW-2 (task_40): HO-6, the duration mode ----
    observe.add_argument(
        "--duration",
        type=_positive_seconds,
        default=None,
        help=(
            "keep observing for this many seconds, repeating the --min-samples "
            "window until it elapses (box-day step S19); absent = one window"
        ),
    )
    # ---- END CARD HW-2 ----

    run = subparsers.add_parser("run", help="armed, one-axis-at-a-time commissioning steps")
    run.add_argument("--config", default=str(default_config))
    run.add_argument("--operator", required=True, help="who is running this, by name")
    run.add_argument("--robot-serial", required=True)
    run.add_argument(
        "--ack",
        action="append",
        default=[],
        choices=sorted(REQUIRED_ACKNOWLEDGEMENTS),
        help="repeat once per required acknowledgement",
    )
    run.add_argument(
        "--mode",
        action="append",
        type=int,
        default=[],
        help="a mode the observe phase saw; repeat for each",
    )
    run.add_argument(
        "--axis",
        action="append",
        choices=[axis.value for axis in CommissioningAxis],
        default=None,
        help="axis to commission; repeat for several (default: all three)",
    )
    run.add_argument("--speed", type=float, default=DEFAULT_LINEAR_SPEED_MPS)
    run.add_argument("--yaw-speed", type=float, default=DEFAULT_YAW_SPEED_RAD_S)
    run.add_argument("--duration", type=float, default=DEFAULT_DURATION_S)
    run.add_argument(
        "--observation",
        default=None,
        help=(
            "the observe phase's evidence file; without it the record can never "
            "authorize configuration, because nothing witnessed the robot at rest"
        ),
    )
    run.add_argument("--journal", required=True, help="fresh path; a journal is used once")
    run.add_argument("--record-out", required=True)
    run.add_argument("--software-revision", default=f"parcel_robot {__version__}")
    run.add_argument("--artifact", action="append", default=[])
    run.add_argument(
        "--observed-direction",
        action="append",
        default=[],
        metavar="AXIS=DIRECTION",
        help=f"what you saw, e.g. vx=forward; one of {', '.join(_DIRECTIONS)}",
    )
    run.add_argument(
        "--arm",
        action="store_true",
        help="required acknowledgement that this command can move physical hardware",
    )

    review = subparsers.add_parser("review", help="a second person accepts or rejects a record")
    review.add_argument("--record", required=True)
    review.add_argument("--reviewer", required=True, help="must not be the operator")
    review.add_argument("--accept", action="store_true")
    review.add_argument("--notes", default="")
    review.add_argument("--out", default=None)

    apply_parser = subparsers.add_parser(
        "apply", help="print the configuration a reviewed record authorizes"
    )
    apply_parser.add_argument("--record", required=True)
    apply_parser.add_argument("--config", default=str(default_config))
    return parser


def _parse_directions(
    pairs: list[str],
    parser: argparse.ArgumentParser,
) -> dict[CommissioningAxis, ObservedDirection]:
    directions: dict[CommissioningAxis, ObservedDirection] = {}
    for pair in pairs:
        axis_name, _, direction_name = pair.partition("=")
        axis = _enum_member(CommissioningAxis, axis_name.strip())
        direction = _enum_member(ObservedDirection, direction_name.strip())
        if axis is None or direction is None:
            parser.error(
                "--observed-direction must be AXIS=DIRECTION with AXIS in "
                f"{', '.join(axis.value for axis in CommissioningAxis)} and DIRECTION in "
                f"{', '.join(_DIRECTIONS)}; got {pair!r}"
            )
        directions[axis] = direction
    return directions


def _load_observation(
    path: str | None,
    parser: argparse.ArgumentParser,
) -> ObservationEvidence | None:
    """Load the read-only phase's evidence, or ``None`` when none was supplied."""

    if not path:
        return None
    source = Path(path)
    if not source.is_file():
        parser.error(f"--observation {path} does not exist; run the observe subcommand first")
    payload = json.loads(source.read_text())
    if not isinstance(payload, dict):
        parser.error(f"--observation {path} is not an observation evidence document")
    return ObservationEvidence.from_mapping(payload)


def _enum_member(enum_class, value: str):
    """The enum member for ``value``, or ``None`` when there is no such member."""

    try:
        return enum_class(value)
    except ValueError:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _echo(message: str) -> None:
    print(message, flush=True)


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
