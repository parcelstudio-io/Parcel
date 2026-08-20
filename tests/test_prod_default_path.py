"""Card R5: the hosted Realtime lane is the DEFAULT production path.

THE INCIDENT THIS FILE EXISTS FOR
---------------------------------
Two owner directives, verbatim: "Make sure the GPT realtime path and its hybrid
path is the default prod path. Only use the legacy voice path for e2e testing
purposes." The failure mode is not a crash — it is a stack that comes up on the
legacy local voice agent while the panel looks *identical*, so the owner spends
a session talking to the wrong brain and only finds out because the answers feel
wrong. Three surfaces have to agree, and each is pinned here:

1. **The launcher** (``scripts/launch_stack.sh``). A BARE launch must require
   the hosted lane and refuse loudly without a credential/config; ``--legacy``
   is the only way onto the local path and it prints an unmissable banner.
2. **The panel** (``ui/index.html``). Typed commands go to
   ``/api/realtime/text`` whenever the lane exists, the box defaults on, and
   the label describes what UNTICKING costs.
3. **The runtime** (``runtime.py``). A legacy turn taken while the lane is
   constructed emits a warning event — visibility, never prohibition, because
   the mic/STT path and the e2e suites still legitimately enter there.

WHY THE LAUNCHER IS TESTED BY RUNNING IT
----------------------------------------
Grepping the script for ``:-1`` would pass on a script that never reads the
variable. So the script is copied into a sandbox ROOT whose ``scripts/``
directory contains nothing else: the run gets all the way through the realtime
gate on real code paths and then dies on the pre-existing "missing executable
script" check, which is the observation point. No service is ever started, no
network is touched, and the sandbox credential is a literal placeholder.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV
from parcel_robot.runtime import (
    TRANSCRIPT_ORIGIN_MIC,
    TRANSCRIPT_ORIGIN_PANEL,
    RobotRuntime,
)

REPO = Path(__file__).resolve().parents[1]
LAUNCH_STACK = REPO / "scripts" / "launch_stack.sh"
PANEL = REPO / "src" / "parcel_robot" / "ui" / "index.html"

#: Never a real credential. The launcher only checks that the variable is
#: non-empty; it never sends it anywhere, and nothing in this file opens a
#: socket.
PLACEHOLDER_KEY = "sk-not-a-real-key-launcher-sandbox"

#: The refusal every "no hosted lane available" arm must contain, so a test
#: cannot pass on a refusal that came from somewhere else entirely.
PROD_REFUSAL = "the hosted Realtime lane is the production path"

#: The banner. Deliberately matched on its loudest line.
LEGACY_BANNER = "LEGACY VOICE PATH — E2E TESTING ONLY"

#: Where the sandbox run is expected to stop: the pre-existing check that the
#: sibling launch scripts exist. Reaching it means the realtime gate passed.
SANDBOX_STOP = "missing executable script"


# ===================================================== the launcher, executed
def _sandbox(
    tmp_path: Path, *, with_config: bool, enabled: bool = True, name: str = "root"
) -> Path:
    """A ROOT holding only launch_stack.sh and a stub interpreter."""

    root = tmp_path / name
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(LAUNCH_STACK, root / "scripts" / "launch_stack.sh")
    (root / ".parcel" / "bin").mkdir(parents=True)
    python = root / ".parcel" / "bin" / "python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    (root / "configs").mkdir()
    if with_config:
        config = root / "configs" / "realtime.yaml"
        config.write_text(
            f"enabled: {'true' if enabled else 'false'}\nmode: text\n", encoding="utf-8"
        )
    return root


def _run(
    root: Path,
    *args: str,
    key: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    home = root.parent / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        # A path that cannot exist, so the developer's real ~/.config/parcel
        # credential is never read by a test on this machine.
        "PARCEL_REALTIME_ENV": str(root / "absent.env"),
    }
    if key is not None:
        env["OPENAI_API_KEY"] = key
    env.update(env_extra or {})
    return subprocess.run(
        ["/bin/bash", str(root / "scripts" / "launch_stack.sh"), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_a_bare_launch_requires_the_hosted_lane_and_refuses_without_a_credential(
    tmp_path: Path,
) -> None:
    """THE seed catcher for "launcher default regressed to 0".

    No flag, no credential: the run must REFUSE. With the old default this same
    invocation started a legacy stack and said nothing, which is the incident.
    """

    result = _run(_sandbox(tmp_path, with_config=True))
    assert result.returncode != 0
    assert PROD_REFUSAL in result.stderr, result.stderr
    assert "needs a credential" in result.stderr
    assert LEGACY_BANNER not in result.stdout, (
        "a missing credential must refuse, never fall back to the legacy path"
    )
    assert SANDBOX_STOP not in result.stderr, "it must refuse BEFORE anything starts"


def test_a_bare_launch_with_the_credential_and_config_comes_up_on_the_hosted_lane(
    tmp_path: Path,
) -> None:
    """The card's live-proof precondition, as an offline test.

    A bare launch on a machine that HAS the owner's key and config must reach
    "Realtime lane: enabled (production path)" with no flag at all.
    """

    result = _run(_sandbox(tmp_path, with_config=True), key=PLACEHOLDER_KEY)
    assert "Realtime lane: enabled (production path)" in result.stdout, result.stdout
    assert LEGACY_BANNER not in result.stdout
    # It got past the realtime gate and stopped where the sandbox ends.
    assert SANDBOX_STOP in result.stderr


def test_a_bare_launch_refuses_when_the_config_file_is_absent(tmp_path: Path) -> None:
    """The repo ships no configs/realtime.yaml, and prod-default does not change
    that: the LAUNCHER defaults on, the committed credential surface does not."""

    result = _run(_sandbox(tmp_path, with_config=False), key=PLACEHOLDER_KEY)
    assert result.returncode != 0
    assert PROD_REFUSAL in result.stderr
    assert "realtime.yaml" in result.stderr
    assert "--legacy" in result.stderr, "the refusal must name the e2e-only escape hatch"


def test_a_config_that_is_not_enabled_refuses_rather_than_launching_quietly(
    tmp_path: Path,
) -> None:
    result = _run(_sandbox(tmp_path, with_config=True, enabled=False), key=PLACEHOLDER_KEY)
    assert result.returncode != 0
    assert "enabled: true" in result.stderr
    assert LEGACY_BANNER not in result.stdout


def test_the_legacy_flag_is_the_only_quiet_path_and_it_is_not_quiet(
    tmp_path: Path,
) -> None:
    """``--legacy`` disables the lane, and says so unmissably."""

    result = _run(_sandbox(tmp_path, with_config=True), "--legacy")
    assert LEGACY_BANNER in result.stdout, result.stdout
    assert "Reason: --legacy was passed." in result.stdout
    assert "NOT the production path" in result.stdout
    assert PROD_REFUSAL not in result.stderr, "--legacy must not require a credential"
    assert SANDBOX_STOP in result.stderr, "it continues past the gate, it does not refuse"


def test_the_environment_switch_prints_the_same_banner_and_names_itself(
    tmp_path: Path,
) -> None:
    """``PARCEL_ENABLE_REALTIME=0`` is the other way onto the legacy path, and a
    stack that got there through an inherited environment variable is exactly
    the one whose operator does not know it happened."""

    result = _run(
        _sandbox(tmp_path, with_config=True), env_extra={"PARCEL_ENABLE_REALTIME": "0"}
    )
    assert LEGACY_BANNER in result.stdout
    assert "Reason: PARCEL_ENABLE_REALTIME=0" in result.stdout


def test_the_realtime_flag_is_still_accepted_and_changes_nothing(tmp_path: Path) -> None:
    """Muscle memory must keep working: every note in scrum/ says --realtime."""

    bare = _run(_sandbox(tmp_path, with_config=True, name="bare"), key=PLACEHOLDER_KEY)
    flagged = _run(
        _sandbox(tmp_path, with_config=True, name="flagged"), "--realtime", key=PLACEHOLDER_KEY
    )
    assert flagged.returncode == bare.returncode
    assert "Realtime lane: enabled (production path)" in flagged.stdout
    assert LEGACY_BANNER not in flagged.stdout


def test_the_help_text_states_the_default_and_the_e2e_only_escape(tmp_path: Path) -> None:
    result = _run(_sandbox(tmp_path, with_config=True), "--help")
    assert result.returncode == 0
    assert "PRODUCTION path and is ON by default" in result.stdout
    assert "--legacy" in result.stdout
    assert "E2E TESTING ONLY" in result.stdout
    assert "PARCEL_ENABLE_REALTIME=0|1 (default 1" in result.stdout


def test_the_launcher_hands_the_runtime_the_config_it_validated() -> None:
    """The launcher checks one file; the runtime must load that same file.

    Both resolve ``PARCEL_REALTIME_CONFIG`` today, so this is defence in depth
    rather than a live bug — but "validated A, loaded B" is precisely how a
    stack ends up believing it is on the hosted lane while it is not.
    """

    source = LAUNCH_STACK.read_text(encoding="utf-8")
    assert f'export {REALTIME_CONFIG_ENV}="$REALTIME_YAML"' in source


# ============================================================== the panel (A.2)
def test_typed_commands_go_to_the_hosted_lane_whenever_it_exists() -> None:
    """No silent fallback, ever: the realtime branch returns after its error."""

    source = PANEL.read_text(encoding="utf-8")
    assert 'if (el("realtime-live").checked && state.realtime) {' in source
    assert 'await postJson("/api/realtime/text", { text: clean });' in source
    # The either/or rule, pinned as control flow rather than as a comment: the
    # realtime branch RETURNS after surfacing its error. Drop that `return;` and
    # a refused live turn silently re-runs on the local agent — two authorities
    # for one sentence, which is what the restricted ingress exists to prevent.
    assert (
        "          state.localChat.push({ role: \"error\", text: `Live session refused: "
        "${error.message}`, timestamp: new Date().toISOString() });\n"
        "          renderLogs(state.snapshot);\n"
        "        }\n"
        "        return;\n"
        "      }"
    ) in source, "the live branch must return; a fallback to /api/voice/text is never silent"


def test_the_live_box_defaults_on_and_then_remembers_the_owners_choice() -> None:
    """Card R1.6's default-on wiring is load-bearing for R5 and must survive."""

    source = PANEL.read_text(encoding="utf-8")
    assert "if (!state.realtimeToggleTouched && !live.checked) {" in source
    assert "state.realtimeToggleTouched = true;" in source


def test_the_toggle_label_says_what_unticking_costs() -> None:
    """THE seed catcher for a label that still reads as an opt-IN.

    "Send to the live hosted session" described a feature you could add. The box
    is now on by default and unticking it drops the panel onto the e2e-testing
    path, so the label has to name that path.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert "Legacy path (e2e testing only)" in source
    assert "Live hosted session · the production path" in source
    assert "function renderLiveToggleLabel()" in source
    # Rendered on every poll AND on the change event, so the warning cannot lag.
    assert source.count("renderLiveToggleLabel();") >= 2
    assert 'label.classList.toggle("legacy-warning", legacy);' in source
    assert ".realtime-toggle .legacy-warning" in source


def test_the_recent_panel_fixes_are_still_in_place() -> None:
    """R4L's post-close addendum fixed two live defects in this same file.

    They are not this card's work, and this card touched the same file, so the
    cheapest possible guard against clobbering them lives here.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert "function clearMotionInputs" in source
    assert "renderLogs" in source
    assert "state.localChat" in source


# ================================================= card R9: Space IS the e-stop
# Owner policy ruling, 2026-08-19, verbatim: "Space bar should be the e-stop.
# In voice command it should be 'Die Stop'."
#
# The panel is HTML with no test runner of its own, so these are source pins in
# the same style as the toggle-label pins above: they read `index.html` and
# assert on the exact strings the wiring is made of. That is weaker than driving
# a browser and it is honest about being weaker — but the defect class they
# catch is a silent EDIT, not a runtime bug, and an edit shows up in the source.
#: The Space branch, whole. Kept as one block so that reordering it (guard after
#: the branch) or swapping the action fails the pin rather than passing on two
#: independently-present substrings.
_SPACE_BRANCH = """    window.addEventListener("keydown", (event) => {
      if (isTypingTarget(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.code === "Space") {"""


def test_space_latches_the_emergency_stop_and_not_the_nominal_stop() -> None:
    """THE seed catcher for "Space reverts to nominal stop".

    Before the ruling this handler posted ``{action: "stop"}`` — the NOMINAL
    stop, which cancels active motion and leaves the dog armed and drivable on
    the very next arrow key. The owner has said Space IS the e-stop, so it must
    post the same ``emergency_stop`` the red button posts, and the latch must be
    the thing that survives: a nominal stop under the owner's thumb in an
    emergency is the failure this pin exists to make loud.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert _SPACE_BRANCH in source, "the Space branch is not where/what it was"
    space_branch = source.split('if (event.code === "Space") {', 1)[1].split("return;", 1)[0]
    assert '{ action: "emergency_stop" }' in space_branch
    assert '{ action: "stop" }' not in space_branch, "Space must never be the nominal stop"
    # The held dead-man keys are dropped in the same breath. Without this the
    # owner's other hand is still on an arrow key, the latch goes up, and the
    # queued velocity is the first thing waiting when the latch is released.
    assert "clearMotionInputs();" in space_branch
    assert space_branch.index("clearMotionInputs();") < space_branch.index("postJson(")
    # The nominal Stop button keeps its own meaning — the ruling moved Space,
    # not the button next to it.
    assert '<button class="action-button stop" data-action="stop">' in source
    assert 'data-action="emergency_stop"' in source


def test_the_typing_target_guard_still_stands_in_front_of_the_latch() -> None:
    """THE seed catcher for "the typing-target guard removed (typing latches)".

    A space inside the chat box is a space, not an emergency. The guard runs
    BEFORE the Space branch is even reached — pinned as one block above — and it
    has to keep covering every text-entry surface, including contenteditable.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert "function isTypingTarget(target) {" in source
    guard = source.split("function isTypingTarget(target) {", 1)[1].split("}", 1)[0]
    for surface in ("HTMLInputElement", "HTMLTextAreaElement", "HTMLSelectElement", "isContentEditable"):
        assert surface in guard, f"{surface} left the typing guard"
    assert _SPACE_BRANCH in source, "the guard must stay AHEAD of the Space branch"


def test_the_latched_state_is_unmissable_and_carries_its_own_way_out() -> None:
    """THE seed catcher for "the latch is announced but not releasable".

    A latch the owner can trip with one thumb has to say so from anywhere on the
    page, and the way back out has to be inside the thing that announced it. The
    banner is driven by the SAME snapshot field as the e-stop badge, so a latch
    the panel did not itself request — a spoken "Die stop", a watchdog, another
    tab — raises it just the same.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert 'id="estop-banner"' in source
    assert 'role="alert"' in source and 'aria-live="assertive"' in source
    assert 'el("estop-banner").hidden = !emergencyStopped;' in source
    # The release affordance is wired by the SAME [data-action] loop as every
    # other panel action: one code path to the runtime, not a second private one.
    assert (
        '<button type="button" id="estop-release" class="estop-release" '
        'data-action="clear_emergency_stop">' in source
    )
    assert source.count('data-action="clear_emergency_stop"') >= 2, "banner + panel button"


def test_the_panel_says_where_the_space_bar_works_and_where_it_does_not() -> None:
    """The focus caveat, in the panel rather than only in a status doc.

    Browser keys need this page focused (B14's cousin), and the MuJoCo window
    has its own separate keyboard surface that this card did not touch. An owner
    who believes Space is a hardware e-stop is the person this line is for.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert "<strong>Space latches the emergency stop</strong>" in source
    assert "only while this browser page has keyboard focus" in source
    assert "the simulator window has its own separate keyboard controls" in source
    # The keycap moved with the meaning. Leaving <kbd>Space</kbd> on the nominal
    # Stop button — where it sat until this card — would be a panel that
    # documents the opposite of what it does, in the one place the binding is
    # ever written down for the owner. Exactly one button may claim the key.
    assert (
        '<button class="action-button emergency" data-action="emergency_stop">'
        "Emergency stop<kbd>Space</kbd>"
    ) in source
    assert source.count("<kbd>Space</kbd>") == 1, "two buttons cannot both own the Space bar"


# ============================================================ the runtime (A.3)
BACKEND_NAME = "r5-prod-default"


class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("Understood.")


def _runtime(tmp_path: Path) -> RobotRuntime:
    path = tmp_path / "r5.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: true
  log_dir: {tmp_path / "duplex-logs"}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r5 prod-default fixture",
        ),
    )


def _lane_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RobotRuntime:
    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    return _runtime(tmp_path)


def _legacy_warnings(runtime: RobotRuntime) -> list[dict[str, object]]:
    return [
        event
        for event in runtime.snapshot()["events"]  # type: ignore[index]
        if isinstance(event, dict)
        and isinstance(event.get("detail"), dict)
        and event["detail"].get("path") == "legacy_voice"  # type: ignore[union-attr]
    ]


def test_a_legacy_turn_while_the_lane_is_up_is_warned_about_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE seed catcher for "the legacy-turn warning removed".

    Both halves matter. The turn is still HANDLED — the mic/STT path and the
    e2e suites are the legacy path's remaining customers and refusing would
    break the only voice input that exists today — and it is now VISIBLE.
    """

    runtime = _lane_on(tmp_path, monkeypatch)
    try:
        assert runtime.realtime_lane is not None, "the fixture must build a lane"
        assert _legacy_warnings(runtime) == []

        runtime.submit_voice_text("walk forward", origin=TRANSCRIPT_ORIGIN_PANEL)

        warnings = _legacy_warnings(runtime)
        assert len(warnings) == 1, "one turn, one warning"
        event = warnings[0]
        assert event["level"] == "warning"
        assert "legacy voice path handled a turn while the live lane is up" in str(event["text"])
        assert "e2e testing only" in str(event["text"])
        detail = event["detail"]
        assert isinstance(detail, dict)
        assert detail["origin"] == TRANSCRIPT_ORIGIN_PANEL
        assert detail["lane_constructed"] is True
        assert detail["lane_active"] is False, "no session was opened in this test"
    finally:
        runtime.close()


def test_the_warning_names_the_origin_so_a_mic_turn_is_distinguishable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A panel turn is a mistake; a mic turn is the gateway gap. Same event,
    different meaning, so the origin has to ride along."""

    runtime = _lane_on(tmp_path, monkeypatch)
    try:
        runtime.submit_voice_text("hello there", origin=TRANSCRIPT_ORIGIN_MIC)
        warnings = _legacy_warnings(runtime)
        assert len(warnings) == 1
        assert warnings[0]["detail"]["origin"] == TRANSCRIPT_ORIGIN_MIC  # type: ignore[index]
        assert f"origin={TRANSCRIPT_ORIGIN_MIC}" in str(warnings[0]["text"])
    finally:
        runtime.close()


def test_a_partial_hypothesis_does_not_warn_once_per_keystroke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The event deque is 100 slots shared with every source in the runtime.

    One warning per partial would flush the log it is trying to be read in — so
    the warning is final-turns-only, deliberately, and this pins that choice.
    """

    runtime = _lane_on(tmp_path, monkeypatch)
    try:
        for partial in ("w", "wa", "wal", "walk"):
            runtime.submit_voice_text(partial, is_final=False, origin=TRANSCRIPT_ORIGIN_PANEL)
        assert _legacy_warnings(runtime) == []
        runtime.submit_voice_text("walk forward", origin=TRANSCRIPT_ORIGIN_PANEL)
        assert len(_legacy_warnings(runtime)) == 1
    finally:
        runtime.close()


def test_with_no_lane_constructed_the_legacy_path_is_the_only_path_and_stays_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag off is not a misconfiguration: it is a stack with no hosted lane at
    all, where the local agent IS the product. Warning there would be noise."""

    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        assert runtime.realtime_lane is None
        runtime.submit_voice_text("walk forward", origin=TRANSCRIPT_ORIGIN_PANEL)
        assert _legacy_warnings(runtime) == []
    finally:
        runtime.close()


def test_the_hosted_front_door_is_still_refused_to_legacy_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1's binding constraint is untouched by R5: making the legacy path
    VISIBLE must not soften the wall between the two ingresses."""

    runtime = _lane_on(tmp_path, monkeypatch)
    try:
        with pytest.raises(ValueError) as caught:
            runtime.submit_voice_text("hello", origin="realtime")
        assert "submit_realtime_transcript" in str(caught.value)
        assert _legacy_warnings(runtime) == [], "a refused call is not a handled turn"
    finally:
        runtime.close()
