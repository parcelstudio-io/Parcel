"""Card TRUTH-1: the remedies and the reports tell the truth about this box.

WHAT THIS FILE PINS
-------------------
Four operator-facing texts and one config door said something false about this
tree, and each one cost a session morning:

* a D455 remedy that sent a DESK operator to an Orin for ``pyrealsense2`` —
  which is an ordinary pip wheel, is declared by this project's own
  ``camera-realsense`` extra, and was already installed in ``.parcel/``;
* a companion claim that no wheel exists for "3.11+" / aarch64, never measured
  and false (a cp314 wheel is what this interpreter imports);
* ``record --check`` reporting "reader deps present" for six ``d455.*`` rows on
  a box with no camera, because its census asked ``find_spec`` and nothing else;
* a replay report that could not tell a wall-indexed ``audio_end_ms`` from an
  appended-audio one, and a docstring claiming three offline modes could not
  reach ``lane`` when every one of them does;
* ``web_panel.build_runtime`` reading a config section the SHA-locked base omits
  and no overlay could introduce, so the planner LLM could never be turned on.

Each row below pins the corrected text as a PROPERTY OF THE PRODUCT — through
``clockmap.main()``, through the real ``record --check`` CLI in a subprocess,
through the tool's own ``replay()`` on a real ``RealtimeLane`` — never against a
copy of the string. A test that quotes the sentence back to itself passes for
the stale sentence too.

THE STALE-STRING RULE
---------------------
A retracted claim is kept dead by a grep for it, so a retraction that reproduces
the claim verbatim defeats its own guard. Every row here that counts occurrences
of a stale sentence therefore also holds the correction to describing the claim
rather than quoting it. This was a real defect twice in this card's own drafts
(``__init__.py``'s aarch64 retraction, and the replay tool's ``lane`` one).

WHAT IS NOT HERE
----------------
Every attached-camera arm, every hosted ``--replay`` number and every
through-air AIR-1 row. No hardware is on hand except the reSpeaker XVF3800 mic
array, which this file never opens, plays through or writes to.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---- CARD GATE-0b skip-with-reason (scrum/20260822/task_30) — the fence for
# this import is the trailing marker on the very next line, so the import block
# stays one sorted block (ruff I001).
from _external_roots import skip_unless  # ---- END CARD GATE-0b ----

from parcel_robot.realtime.config import realtime_config_from_mapping
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    session_created,
    speech_started,
    speech_stopped,
)
from parcel_robot.realtime.transport import transport_pair
from scripts.parcel_capture import preflight
from scripts.parcel_capture.clockmap import (
    DEFAULT_MODULE_MISSING_REMEDY,
    MODULE_MISSING_REMEDIES,
    module_missing_remedies,
)
from scripts.parcel_capture.clockmap import main as clockmap_main
from scripts.parcel_capture.ingest.realsense import RealSenseIngest

REPO = Path(__file__).resolve().parents[1]

#: The pip line the D455 remedy must carry, everywhere it is stated. Written out
#: rather than composed, because this is the sentence an operator copies.
PIP_LINE = "pip install -e '.[camera-realsense]'"

#: The vendor-SDK sentence. It is TRUE of the go2 and the L2 and false of the
#: D455, which is the entire content of finding SDK-REM-1.
ORIN_ROS2_SENTENCE = "Orin inside the ROS 2 Humble environment"

#: The wheel census, measured from PyPI on 2026-08-22 and re-measured whole on
#: 2026-08-23 (``~/.cache/parcel-truth1/evidence/wheel_census_20260823.txt``):
#: pyrealsense2 2.58.3.10794 ships 13 files and aarch64 covers cp39/cp310/cp312
#: ONLY. This constant is the census the TEXTS have to agree with; it is not
#: re-fetched here, because a unit test that reaches PyPI is a network flake and
#: the census is dated in the texts for exactly that reason.
AARCH64_INTERPRETERS = "cp39/cp310/cp312"


# ============================================================ R1 — clockmap
def _clockmap_check(monkeypatch: pytest.MonkeyPatch, hide: tuple[str, ...]) -> tuple[str, int]:
    """``clockmap --check`` through the PRODUCT ``main()``, modules narrowed.

    Nothing is faked but ``importlib.util.find_spec``: the census then sees the
    vendor SDKs absent exactly the way it would on a bare host, and everything
    downstream — the refusal, the grouping, the exit code — is the real code.
    """

    real = importlib.util.find_spec

    def narrowed(name: str, package: str | None = None) -> Any:
        if name in hide or any(name.startswith(f"{h}.") for h in hide):
            return None
        return real(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", narrowed)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = clockmap_main(["--check"])
    return buffer.getvalue(), code


def test_the_module_missing_paragraph_gives_the_d455_its_own_remedy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1. One line per REMEDY, not one line for every device that is absent.

    ENV-1b split "the SDK is missing" from "the cable is missing" but left a
    single sentence covering all three devices, so a desk operator whose
    ``pyrealsense2`` import failed was told to go find an Orin. The go2 and the
    L2 genuinely do need the vendor ROS 2 environment; the D455 never did.
    """

    out, code = _clockmap_check(
        monkeypatch, ("rclpy", "cyclonedds", "pyrealsense2", "unitree_lidar_sdk_pybind")
    )

    paragraph = out.split("MODULE MISSING")[1].split("Recording a session without")[0]
    d455_line = next(ln for ln in paragraph.splitlines() if ln.strip().startswith("d455:"))
    vendor_line = next(ln for ln in paragraph.splitlines() if ln.strip().startswith("go2, l2:"))

    assert PIP_LINE in d455_line, "the D455's remedy must be the pip line an operator can run"
    assert d455_line.count(ORIN_ROS2_SENTENCE) == 0, (
        "the D455 remedy still sends a desk operator to an Orin for a pip wheel"
    )
    assert vendor_line.count(ORIN_ROS2_SENTENCE) >= 1, (
        "the go2/L2 remedy is TRUE and must survive: those SDKs are vendor builds"
    )

    # The existing contract, unchanged. A card that improves a refusal's wording
    # and quietly stops refusing has made the tree worse.
    assert code == 2
    assert "REFUSED" in out
    assert "permanently unrecoverable" in out


def test_the_remedy_table_groups_devices_and_defaults_to_the_vendor_sentence() -> None:
    """R1's seam, directly: grouping is stable and an unmeasured device is vendor.

    ``module_missing_remedies`` is a pure function so the paragraph's shape can
    be pinned without running the whole census. The DEFAULT matters as much as
    the entries: a device nobody has measured is a vendor device until someone
    does, which is the conservative direction and the one that was only ever
    wrong for the D455.
    """

    assert MODULE_MISSING_REMEDIES["go2"] == DEFAULT_MODULE_MISSING_REMEDY
    assert MODULE_MISSING_REMEDIES["l2"] == DEFAULT_MODULE_MISSING_REMEDY
    assert MODULE_MISSING_REMEDIES["d455"] != DEFAULT_MODULE_MISSING_REMEDY

    grouped = module_missing_remedies(["l2", "d455", "go2"])
    assert [names for _remedy, names in grouped] == [("d455",), ("go2", "l2")], (
        "the go2 and the L2 share one true sentence; the D455 gets its own"
    )
    assert module_missing_remedies(["mid360"]) == ((DEFAULT_MODULE_MISSING_REMEDY, ("mid360",)),), (
        "a device with no measured entry must fall back to the vendor sentence"
    )


# =========================================== R2 / R3 / R5 — the three sites
def test_the_adapter_remedy_names_the_extra_and_carries_the_dated_census() -> None:
    """R2. ``RealSenseIngest.requirements[0].remedy``.

    This is the string ``IngestAdapter.probe_availability`` puts in front of an
    operator and the one ``IngestUnavailableError.remedy`` carries into the
    traceback. Both stale claims are counted at zero, and the replacement has to
    be DATED — an environment claim with no date is one nobody knows to
    re-measure.
    """

    remedy = RealSenseIngest.requirements[0].remedy

    assert PIP_LINE in remedy
    assert remedy.count("Orin only") == 0, "pyrealsense2 is not Orin-only; it is a pip wheel"
    assert remedy.count("no wheel exists for 3.11+") == 0, (
        "that claim was never measured and is false — a cp314 wheel is installed here"
    )
    assert "2026-08-22" in remedy, "an environment claim with no date is one nobody re-measures"
    assert AARCH64_INTERPRETERS in remedy, "the census is what makes the claim checkable"


def test_the_preflight_realsense_remedy_is_a_pip_line_and_the_vendors_stay_vendors() -> None:
    """R3, and the one row this card MISSES as registered — see the status doc.

    Registered at 15:27 on 2026-08-22: ``Orin`` occurrences in the realsense
    remedy = 0. At 16:00 the owner named the Go2 EDU+ with its onboard Orin NX
    as the real deploy host, which makes an Orin-free D455 remedy the same lie
    pointing the other way: the operator who reads it on the dog is told nothing
    about the dog. The truthful remedy names BOTH hosts and says what is true on
    each, so the count is 1 and the row is reported as a MISS rather than
    quietly relaxed.

    The number is pinned HERE too, so that if someone later decides the
    registered 0 was right, this test reddens and the decision is deliberate.
    """

    realsense = preflight._TRANSPORT_MODULES["realsense"][1]

    assert PIP_LINE in realsense
    assert realsense.count("Orin only") == 0
    assert realsense.count("Orin") == 1, (
        "registered pass was 0; the measured value is 1 and is reported as a MISS "
        "in TRUTH1_STATUS.md — the Orin is named once, as the SECOND host, not as "
        "the place a desk operator must go"
    )
    assert "UNCONFIRMED" in realsense, (
        "which JetPack the EDU dock boots decides whether pip works at all; the "
        "remedy must not pretend that is settled"
    )

    # The four vendor transports keep the sentence that is true of them.
    for transport in ("dds", "vendor_video", "vendor_uwb", "unilidar_sdk2"):
        assert preflight._TRANSPORT_MODULES[transport][1].count("Orin") >= 1, (
            f"{transport}'s SDK really is a vendor build that exists nowhere else"
        )


# ---- CARD GATE-0b skip-with-reason (scrum/20260822/task_30) ----------------
# The D455 branch this row measures is only reachable with the optional
# `pyrealsense2` wheel installed (it is, on this box). A clean `[dev,voice]`
# clone has neither the wheel nor that branch, and the row went red there for
# a reason that is about the wheelhouse, not about TRUTH-1's text. Decoration
# only: no assertion, pin or count below this line is GATE-0b's.
@skip_unless("pyrealsense2")
# ---- END CARD GATE-0b ------------------------------------------------------
def test_the_preflight_identity_probe_has_its_own_true_remedy_per_branch() -> None:
    """R3's second site, found by the verifier (F1) — `preflight.probe_d455`.

    `run_preflight` calls `probe_d455`, whose ABSENT observations are rendered
    with their remedy in the preflight report. R3's registration named only
    `_TRANSPORT_MODULES`, so this site went unmeasured in the first pass and
    still read "install pyrealsense2 in the Orin capture environment" — on a box
    where `pyrealsense2` IS installed and where no Orin exists. SDK-REM-1
    verbatim, one function away from the site the card fixed.

    The two branches are two different facts. On THIS box the module is present,
    so the branch taken is "no live identity reader" and the remedy must not
    mention installing anything; hide the module and the pip text appears.
    """

    from scripts.parcel_capture.preflight import probe_d455

    # --- the branch this box actually takes -----------------------------------
    present = probe_d455()[0]
    assert present.absence is not None and present.absence.value == "not_attempted"
    assert "install pyrealsense2 in the Orin capture environment" not in present.remedy, (
        "the module-present branch printed the module-missing remedy: SDK-REM-1"
    )
    assert "importable here" in present.remedy, (
        "the remedy must say WHY this is not a wheel problem"
    )
    assert "Do not pip install anything for this row." in present.remedy

    # --- the branch a bare host takes -----------------------------------------
    real = importlib.util.find_spec

    def narrowed(name: str, package: str | None = None) -> Any:
        return None if name == "pyrealsense2" else real(name, package)

    original = importlib.util.find_spec
    importlib.util.find_spec = narrowed  # type: ignore[assignment]
    try:
        missing = probe_d455()[0]
    finally:
        importlib.util.find_spec = original  # type: ignore[assignment]

    assert missing.absence is not None and missing.absence.value == "dependency_missing"
    assert PIP_LINE in missing.remedy, "the module-missing branch is the pip line, per host"
    assert AARCH64_INTERPRETERS in missing.remedy
    assert "UNCONFIRMED" in missing.remedy, "which JetPack the dock boots is not settled"


def test_the_package_docstring_retracts_the_aarch64_claim_without_quoting_it() -> None:
    """R5, and the stale-string rule stated in this file's header.

    The first draft of this correction retracted the claim by quoting it, which
    left the grep at 1 — the guard would have been defeated by the very
    paragraph that fixed it. The retraction describes the claim instead.
    """

    text = (REPO / "scripts" / "parcel_capture" / "__init__.py").read_text(encoding="utf-8")

    assert text.count("there is no aarch64 build") == 0, (
        "the stale claim is kept dead by this grep; do not quote it, describe it"
    )
    assert AARCH64_INTERPRETERS in text, "the replacement must carry the measured census"
    assert "13 files" in text
    assert "2026-08-22" in text


# ============================================================ R4 — --check
# ---- CARD GATE-0b skip-with-reason (scrum/20260822/task_30) ----------------
# Same reason as the decoration above: `record --check` can only print
# "NO DEVICE (installed: pyrealsense2)" on a host that has the wheel. R4's
# measured row and its exit code are untouched.
@skip_unless("pyrealsense2")
# ---- END CARD GATE-0b ------------------------------------------------------
def test_check_says_no_device_for_a_camera_nobody_owns() -> None:
    """R4, through the real CLI in a subprocess — its own stdout, its own exit code.

    A subprocess and not an in-process call because the row that was wrong was
    what the OPERATOR sees when they type the command, and because
    ``dependency_report_text()``'s missing product caller is only observable
    from outside: before this card the function existed and a test was the only
    thing that ever called it.
    """

    proc = subprocess.run(
        [sys.executable, "-m", "scripts.parcel_capture.record", "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
        # `--check` exits 3 on this box BY DESIGN (rclpy/unilidar/tegrastats/ffmpeg
        # are absent), so a raising call would fail the row it is measuring. The
        # exit code is asserted below instead of delegated.
        check=False,
    )
    out = proc.stdout

    assert out.count("reader deps present") == 0, (
        "a module-only census reported a device present; that is the defect"
    )
    d455_rows = [ln for ln in out.splitlines() if ln.strip().startswith("d455.")]
    assert len(d455_rows) == 6, f"expected the six d455 channels, saw {len(d455_rows)}"
    for row in d455_rows:
        assert "NO DEVICE" in row, (
            f"realsense declares /dev/video* and nothing is attached: {row.strip()}"
        )

    assert out.count("NO DEVICE (installed: pyrealsense2)") >= 1, (
        "ENV-1's adapter-level block must have a PRODUCT caller, not just a test"
    )
    assert proc.returncode == 3, (
        "--check's exit code is about modules and space; this card must not move it"
    )


def test_check_never_calls_an_unattestable_transport_ready() -> None:
    """R4's other half: "we could not ask" must not read as "it is there".

    ``usb_audio`` creates no ``/dev`` node the census can glob, so the honest
    answer is that the filesystem cannot say — not READY, and not NO DEVICE
    either, which would be a claim nobody measured.
    """

    proc = subprocess.run(
        [sys.executable, "-m", "scripts.parcel_capture.record", "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,  # exit 3 is the expected outcome here; see the row above
    )
    mic = next(ln for ln in proc.stdout.splitlines() if ln.strip().startswith("mic.xvf3800"))
    assert "DEVICE NOT ATTESTABLE" in mic, mic
    assert "READY" not in mic, "an unaskable transport must never be called ready"


# ============================================================ R6 — the replay
def _write_wav(path: Path, pcm: bytes, *, rate: int = 16_000) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm)


def _corpus(directory: Path, ids: tuple[str, ...], *, loud_ms: int, total_ms: int) -> None:
    """One 16 kHz WAV per id: ``loud_ms`` of tone, then silence to ``total_ms``."""

    directory.mkdir(parents=True, exist_ok=True)
    loud = b"\x00\x40" * int(16_000 * loud_ms / 1000)
    quiet = b"\x00\x00" * int(16_000 * (total_ms - loud_ms) / 1000)
    for name in ids:
        _write_wav(directory / f"{name}.wav", loud + quiet)


def _load_replay_tool() -> Any:
    """``tools/replay_turn_detection.py``, imported by path.

    By path because ``tools/`` is a folder of scripts the owner runs and
    deliberately not an importable package — but the harness a measurement will
    be taken with still has to be tested, or its numbers are un-auditable.
    """

    path = REPO / "tools" / "replay_turn_detection.py"
    spec = importlib.util.spec_from_file_location("_truth1_replay_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scripted_live_lane(tool: Any, arm: str, script: list[Step]) -> tuple[Any, dict[str, Any]]:
    """A lane shaped exactly like ``_build_live_lane``'s, on an in-process pair.

    Same config path, same ``_NullSink``, same ``open_session`` — only the
    transport is swapped, so everything ``replay()`` does to a hosted session it
    does here. ``pump`` is wrapped to drive the fake server first, which is the
    one thing a real socket does for itself.
    """

    from parcel_robot.realtime.lane import RealtimeLane

    holder: dict[str, Any] = {}

    def factory() -> Any:
        lane_end, server_end = transport_pair()
        holder["server"] = FakeRealtimeServer(transport=server_end, script=list(script))
        return lane_end

    body: dict[str, Any] = {"enabled": True, "mode": "audio"}
    if tool.ARMS[arm]:
        body["turn_detection"] = dict(tool.ARMS[arm])
    lane = RealtimeLane(
        config=realtime_config_from_mapping(body, source=f"arm:{arm}"),
        instructions="truth1 replay harness",
        transport_factory=factory,
        sink_factory=tool._NullSink,
    )
    original_pump = lane.pump

    def pump() -> int:
        server = holder.get("server")
        if server is not None:
            server.pump()
        return original_pump()

    lane.pump = pump  # type: ignore[method-assign]
    holder["lane"] = lane
    return lane, holder


def _frames_per_file(tool: Any, path: Path) -> int:
    """How many 20 ms provider-rate frames one corpus file becomes.

    Computed with the tool's own reader and resampler rather than assumed, so
    the script below lines up with the stream the lane actually sends.
    """

    stream = tool.to_provider_rate(tool.read_pcm(path))
    frame_bytes = int(tool.PROVIDER_RATE_HZ * tool.FRAME_MS / 1000) * 2
    return -(-len(stream) // frame_bytes)


def test_the_replay_report_carries_both_candidate_origins_and_can_tell_them_apart(
    tmp_path: Path,
) -> None:
    """R6. TURN-1's handoff, closed: DETECT a wall-indexed ``audio_end_ms`` and CORRECT it.

    Nothing in this repository settles whether the provider indexes
    ``audio_end_ms`` in appended audio or in the session's wall clock, and on a
    single file the two are the same number because the stream is paced in real
    time. ``--settle-s`` is what separates them: each settle window adds wall
    milliseconds and no audio milliseconds. So this drives the tool's own
    ``replay()`` over a TWO-file corpus at ``settle_s=0.15`` on a real
    ``RealtimeLane``, and requires the second file to have diverged and the
    first not to have.

    The arithmetic row matters as much as the divergence: a wall column nobody
    can check against ``commits_raw_ms`` is a number, not evidence.
    """

    tool = _load_replay_tool()
    recording = tmp_path / "corpus"
    _corpus(recording, ("01", "02"), loud_ms=300, total_ms=600)
    per_file = _frames_per_file(tool, recording / "01.wav")

    # One Step per client frame. The last append of each file carries that
    # file's speech_started/speech_stopped, so each file produces one commit
    # whose raw audio_end_ms is a provider index into the WHOLE session buffer.
    script: list[Step] = [
        Step("session.update", (session_created("sess_truth1"),), label="handshake")
    ]
    for file_index in range(2):
        for frame_index in range(per_file - 1):
            script.append(
                Step("input_audio_buffer.append", (), label=f"f{file_index}.{frame_index}")
            )
        end_ms = 600 * (file_index + 1)
        script.append(
            Step(
                "input_audio_buffer.append",
                (speech_started(600 * file_index), speech_stopped(end_ms)),
                label=f"commit{file_index}",
            )
        )
    lane, _holder = _scripted_live_lane(tool, "server_vad_default", script)

    out = tmp_path / "results"
    settle_s = 0.15
    assert (
        tool.replay(
            arm="server_vad_default",
            recording=recording,
            live=True,
            settle_s=settle_s,
            out=out,
            build_lane=lambda arm: lane,
        )
        == 0
    )
    report = json.loads((out / "server_vad_default.json").read_text(encoding="utf-8"))

    # --- the report carries settle_s, as a FIELD ---------------------------
    assert report["schema"] == "parcel.turn1.replay.v2"
    assert report["settle_s"] == settle_s, (
        "a report that does not say what settle_s was cannot be read for the "
        "audio_end_ms question at all"
    )

    # --- every row carries all five wall columns ---------------------------
    rows = report["utterance_rows"]
    assert len(rows) == 2
    for row in rows:
        for column in (
            "wall_offset_ms",
            "wall_elapsed_ms",
            "wall_minus_audio_ms",
            "commits_wall_relative_ms",
            "commit_latency_wall_ms",
        ):
            assert column in row, f"{row['utterance_id']} is missing {column}"

    # --- the discrimination row -------------------------------------------
    first, second = rows[0], rows[1]
    assert first["wall_minus_audio_ms"] < 100, (
        f"file 01 is the origin; the two clocks cannot have diverged yet "
        f"({first['wall_minus_audio_ms']} ms)"
    )
    assert second["wall_minus_audio_ms"] >= 100, (
        f"one {settle_s * 1000:.0f} ms settle window separates the two candidate "
        f"origins by design; file 02 shows {second['wall_minus_audio_ms']} ms"
    )
    assert report["wall_minus_audio_ms_max"] == pytest.approx(
        max(row["wall_minus_audio_ms"] for row in rows)
    )

    # --- the arithmetic is checkable from the file alone -------------------
    for row in rows:
        assert row["commits_raw_ms"], "the scripted provider committed on every file"
        expected = row["commits_raw_ms"][0] - row["wall_offset_ms"]
        assert abs(row["commits_wall_relative_ms"][0] - expected) <= 0.1 + 1e-9, (
            f"{row['utterance_id']}: wall-relative commit does not reconcile with "
            f"commits_raw_ms - wall_offset_ms"
        )


# ============================================================ R7 — docstring
def test_the_offline_modes_reach_lane_and_never_reach_ws_transport() -> None:
    """R7. The tool's claim, measured in a subprocess instead of asserted in prose.

    The docstring used to say ``--arms`` / ``--check`` / ``--plan`` could not
    reach ``lane`` even by accident. They all reach it — the realtime package's
    ``__init__`` imports it — so the claim was false and made a TRUE, checkable
    property (``ws_transport`` is the module that opens a socket) look broken.
    A fresh interpreter is the only place this is observable: pytest has already
    imported half the tree.
    """

    probe = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location("
        "'_t', 'tools/replay_turn_detection.py')\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['_t'] = m\n"
        "spec.loader.exec_module(m)\n"
        "rc = m.main(['--arms'])\n"
        "print('RC', rc)\n"
        "print('lane', 'parcel_robot.realtime.lane' in sys.modules)\n"
        "print('ws', 'parcel_robot.realtime.ws_transport' in sys.modules)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=REPO, check=False
    )
    # Asserted rather than delegated to `check=True`: a raised CalledProcessError
    # hides the child's stderr, which is the only thing that says WHY.
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "RC 0" in proc.stdout
    assert "lane True" in proc.stdout, "the offline modes DO import lane; saying otherwise is false"
    assert "ws False" in proc.stdout, (
        "importing ws_transport is what puts a websocket client in the process; "
        "that is the property this file guarantees"
    )

    source = (REPO / "tools" / "replay_turn_detection.py").read_text(encoding="utf-8")
    assert source.count("cannot reach") == 0, (
        "the retracted claim must be described, not reproduced — the grep is the guard"
    )


# ============================================================ R8 — AIR-1 text
def test_the_runbook_leads_with_the_measurements_real_name() -> None:
    """R8. One measurement, one name, in both places a reader looks.

    ``asr_beam_echo_attenuation_db`` is the whole XVF3800 chain — canceller,
    residual suppressor, beamformer rejection and capture gain together —
    whereas textbook ERLE is one stage of it. ``erle_db`` survives as the
    scorecard ROW ID because renaming a pre-registered row id mid-card would
    silently break the >= 20 dB gate's continuity; it is the alias, never the
    name of the number.
    """

    text = (REPO / "scrum" / "20260822" / "task_25" / "SESSION.md").read_text(encoding="utf-8")

    assert "The measured field is **`asr_beam_echo_attenuation_db`**" in text, (
        "the §5 prose must LEAD with the long name"
    )
    gate_rows = [
        line
        for line in text.splitlines()
        if line.strip().startswith("|") and "≥ 20 dB" in line and "step 5A" in line
    ]
    assert len(gate_rows) == 1, gate_rows
    assert gate_rows[0].strip().startswith("| `asr_beam_echo_attenuation_db`"), (
        f"the pre-registered rows table must lead with the long name: {gate_rows[0]}"
    )
    assert "scorecard row id: `erle_db`" in gate_rows[0], "erle_db is shown as the alias"


def test_the_mux_paths_prerequisites_are_stated_once_and_completely() -> None:
    """R8's other half: a prerequisite you assemble from three places is one you
    find out about by failing.

    All three were scattered across step 3, section 5A and two tool docstrings.
    They are now one block, and the third one — never flash the 6-channel image
    — had never been written in this file at all.
    """

    text = (REPO / "scrum" / "20260822" / "task_25" / "SESSION.md").read_text(encoding="utf-8")

    assert text.count("Prerequisites for the mux path") == 1, "one block, not several"
    block = text.split("Prerequisites for the mux path")[1].split("Then check:")[0]
    assert "udev rule" in block and "`pyusb`" in block
    assert "v2.0.6" in block
    assert "Never flash the 6-channel image" in block
    assert text.count("6-channel") >= 1, (
        "the file never mentioned the 6-channel image; the warning has to exist to be read"
    )
    assert "This only works once step 3" not in text, (
        "the scattered half-statement this block replaces must be gone"
    )


# ============================================================ R9 — the door
def _base_config() -> dict[str, Any]:
    from parcel_robot.paths import resolve_config_yaml

    return yaml.safe_load(resolve_config_yaml().read_text(encoding="utf-8")) or {}


def test_an_overlay_may_now_introduce_the_planner_section() -> None:
    """R9. CAP-1's carried finding: a knob that existed and nobody could turn.

    ``web_panel.build_runtime`` reads ``store.section("planner_model")`` to
    decide whether to construct a SECOND llama.cpp provider. ``configs/robot.yaml``
    is SHA-locked and omits the block, and ``planner_model`` was not in
    ``OVERLAY_INTRODUCIBLE_KEYS`` — so with no profile the section read ``{}``
    and the planner could never be enabled, and a profile that tried to set it
    made the whole config load REFUSE. ROAM-1 finding 6, a second time, in the
    product launcher.
    """

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS, check_overlay_keys

    assert "planner_model" in OVERLAY_INTRODUCIBLE_KEYS
    assert not any(key.startswith("planner_model.") for key in OVERLAY_INTRODUCIBLE_KEYS), (
        "the loader stops descending at an exempt parent, so listing the children "
        "would look like a spelling guard and be inert"
    )
    check_overlay_keys(_base_config(), {"planner_model": {"enabled": True}})


def test_the_planner_default_is_still_off() -> None:
    """R9's standing rule: nothing here turns anything on.

    The SHA-locked base still omits the block, so ``build_runtime``'s
    ``planner_config.get("enabled", False)`` is still False on every run that
    does not write one. The entry makes writing one POSSIBLE; it does not write
    one.
    """

    assert "planner_model" not in _base_config(), (
        "if the base ever grows the block, this card's whole premise changes"
    )


def test_a_typo_inside_the_planner_section_is_refused_by_name() -> None:
    """R9's typo guard, at the READ SITE — the only thing between a typo and a
    silent default.

    The subtree exemption is deliberate and it means ``check_overlay_keys`` will
    merge ``plan_timeoutt: 5`` without a word. Every introducible family in this
    project answers that the same way: ``CameraStreamConfig.from_section`` for
    the camera family, ``RobotRuntime.roam_config`` for roam, and this for the
    planner. Without it the failure is the ``minimum_confidenc`` failure
    verbatim — the file says ``plan_timeoutt``, the provider is built at the
    shipped default, and nothing says the operator's edit did nothing.
    """

    from parcel_robot.web_panel import _PLANNER_MODEL_KEYS, _check_planner_model_section

    with pytest.raises(ValueError, match="plan_timeoutt"):
        _check_planner_model_section({"enabled": True, "plan_timeoutt": 5})

    assert _check_planner_model_section({"enabled": True, "plan_timeout": 5.0}) == {
        "enabled": True,
        "plan_timeout": 5.0,
    }
    # An absent section is the DEFAULT, not an error: ConfigStore.section returns
    # {} and that is the no-planner case.
    assert _check_planner_model_section({}) == {}
    assert _check_planner_model_section(None) == {}

    # The allow-list is the provider's own vocabulary, not a hand-kept copy that
    # drifts: every key `LlamaCppProvider.from_config` reads must be in it, or a
    # new provider knob makes this guard start refusing a legitimate key — which
    # is the failure mode a read-site guard has and a loader-side one does not.
    source = (REPO / "src" / "parcel_robot" / "providers.py").read_text(encoding="utf-8")
    body = source.split("def from_config", 1)[1].split("\n    def ", 1)[0]
    read = {chunk.split('"', 1)[0] for chunk in body.split('config.get("')[1:]}
    assert read, "from_config's config.get(...) calls could not be located"
    missing = sorted(read - _PLANNER_MODEL_KEYS)
    assert not missing, (
        f"LlamaCppProvider.from_config reads {missing}, which this guard would now "
        f"refuse — add them to web_panel._PLANNER_MODEL_KEYS"
    )
    # And nothing beyond that vocabulary plus `enabled`, which build_runtime reads
    # itself. A guard that allows keys nothing reads is not a guard.
    assert _PLANNER_MODEL_KEYS - read == {"enabled"}, (
        f"the allow-list has drifted from the provider: {sorted(_PLANNER_MODEL_KEYS - read)}"
    )


def _profile_tree(tmp_path: Path, profile: str, planner: dict[str, Any]) -> Path:
    """The shipped base plus a REAL profile overlay, on disk. Card TRUTH-1 / F2.

    No monkeypatching of any product symbol: the base is a byte copy of
    ``configs/robot.yaml`` and the overlay is the sibling file ``ConfigStore``
    itself goes looking for when ``$PARCEL_PROFILE`` is set. This is the path an
    operator actually takes to turn the planner on, which is the only path that
    can prove the guard is WIRED.
    """

    from parcel_robot.paths import resolve_config_yaml

    base = tmp_path / "robot.yaml"
    base.write_text(resolve_config_yaml().read_text(encoding="utf-8"), encoding="utf-8")
    overlay = tmp_path / f"robot.{profile}.yaml"
    overlay.write_text(yaml.safe_dump({"planner_model": planner}), encoding="utf-8")
    return base


def test_build_runtime_refuses_a_misspelled_planner_key_from_a_real_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9 / F2 — the guard is WIRED, not merely present.

    The first pass pinned ``_check_planner_model_section`` as a function. The
    verifier removed the CALL from ``build_runtime``, left the function intact,
    and six tests still passed: a typo would have booted at the shipped default
    with nothing pinning it. DESIGN §(g)2 calls that call "the ONLY thing
    between a typo and a silent default", so it is the call that has to be
    pinned.

    Everything here is the product path: a real base file, a real sibling
    overlay, ``$PARCEL_PROFILE``, and ``build_runtime`` itself. The only
    monkeypatching is of ENVIRONMENT VARIABLES — ``PARCEL_MEMORY_PATH`` so the
    owner's ``parcel_memory.sqlite3`` is never opened (card R27), and
    ``PARCEL_PROFILE`` because that is how a profile is selected.
    """

    profile = "truth1typo"
    base = _profile_tree(tmp_path, profile, {"enabled": True, "plan_timeoutt": 5})
    monkeypatch.setenv("PARCEL_PROFILE", profile)
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))

    from parcel_robot import web_panel

    # The overlay loader MERGES it — by design, the subtree is exempt — so if
    # build_runtime does not check, nothing anywhere refuses.
    from parcel_robot.config import ConfigStore

    assert ConfigStore(base).section("planner_model") == {
        "enabled": True,
        "plan_timeoutt": 5,
    }, "the exemption is what makes the read-site guard load-bearing"

    with pytest.raises(ValueError, match="plan_timeoutt"):
        web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)


def test_build_runtime_accepts_the_same_profile_spelled_correctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: the knob CAN now be turned, which is the point of R9.

    Without the ``OVERLAY_INTRODUCIBLE_KEYS`` entry this raised ``ProfileError``
    at config load and the planner could never be enabled by anyone. A guard
    that refuses the good case as well as the bad one has not fixed anything.
    """

    profile = "truth1good"
    base = _profile_tree(tmp_path, profile, {"enabled": True, "plan_timeout": 5.0})
    monkeypatch.setenv("PARCEL_PROFILE", profile)
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))

    from parcel_robot import web_panel

    runtime = web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)
    assert runtime is not None
    # `use_llm=False` forces the planner off, so no provider is constructed and
    # no socket is opened; what is proved is that the load PASSES the door the
    # typo case is refused at.
    assert runtime.agent.planner_model is None


def test_the_survey_of_unreachable_config_sections_is_now_empty() -> None:
    """R9's closing property, and the one worth keeping after the fix.

    CAP-1 pinned that the set of product-read sections no overlay can introduce
    was EXACTLY ``{"planner_model"}`` so that a second instance would redden and
    so would the fix. The fix landed; ``tests/test_cap1_admission.py`` is updated
    in the same change to assert emptiness. This is the same property asserted
    from this card's side, so removing either one still leaves a guard standing.
    """

    from parcel_robot import admission
    from parcel_robot.admission import DOMAIN_CONFIG_KEY
    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS

    base = _base_config()
    unreachable = {
        name
        for name in admission.product_config_sections()
        if name not in base and name not in OVERLAY_INTRODUCIBLE_KEYS
    }
    assert unreachable == set(), (
        "a product file reads these config sections, the SHA-locked base does not "
        f"define them, and no overlay may introduce them: {sorted(unreachable)}"
    )

    row = next(
        entry
        for entry in admission.admitted()
        if entry.domain == DOMAIN_CONFIG_KEY and entry.name == "planner_model"
    )
    assert row.admitted is True
    assert "OVERLAY_INTRODUCIBLE_KEYS" in row.reason
