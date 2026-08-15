"""One argv truth across every committed Stage-0 sheet — card S-2, fix tranche FX-1.

``scrum/20260814/task_1/STAGE0_COMMAND_ADDENDUM.md`` is generated, and this is
its pin. It is also the pin for the property AU-F's F1 found violated: **three
committed operator sheets, two argv truths.**

What broke (AU-F FX-1 / F1, reproduced before the fix)::

    humble: combined=46 tokens  per-distro=46 tokens
      positional mismatches: [('/data/parcel/session', '/data/parcel/stage0/take01'),
                              ('/data/parcel/mcap_storage.yaml',
                               '/data/parcel/stage0/mcap_storage.yaml')]
    jazzy:  combined=50 tokens  per-distro=50 tokens   (same two mismatches)
    T7 rs_launch.py: sibling omits
      ['camera_name:=camera', 'camera_namespace:=camera',
       'publish_tf:=true', 'tf_publish_rate:=0.0']

Same token counts, different commands — which is why counting tokens was never
enough. ``publish_tf`` / ``tf_publish_rate`` are not cosmetic: S-1's GO-RECORD
gate refuses a bag whose optical frames have no parent, so the combined sheet's
launch line produced a session that could not certify.

The resolution (AU-F authority): the per-distro sheets are the operative pair;
``STAGE0_COMMAND_ADDENDUM.md`` is regenerated as a thin **index** with no
command rows, and :func:`~scripts.parcel_capture.stage0_addendum.render_addendum`
is the only renderer that emits a command.

So this file asserts, over the **committed bytes of every sheet in the card**:

1. the index is byte-identical to ``render_combined_index()`` and contains zero
   command tokens;
2. per distro, every committed recorder argv is the same token list, and equals
   ``record_command`` for that distro;
3. per distro, every committed ``ros2 launch`` line is the same token list —
   which is what F5 (the T7 contradiction) needs;
4. the storage config cannot be nested inside the record target, in the
   constants **and** at construction time (F2);
5. writing a sheet requires an explicit path, and exercising the module the way
   the no-arm harness does leaves the tree byte-identical (F3).

Regenerate with::

    .parcel/bin/python -m scripts.parcel_capture.stage0_addendum --emit
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from scripts.parcel_capture import rosbag2 as rb
from scripts.parcel_capture import stage0_addendum as s0

#: Minimal Humble ``ros2 bag record --help`` flag set — enough for
#: ``validate_argv_against_help`` (must include --output/--storage/--max-cache-size).
HUMBLE_HELP = """
usage: ros2 bag record [-h] [--output OUTPUT] [--storage STORAGE]
  --output OUTPUT
  --storage STORAGE
  --max-cache-size MAX_CACHE_SIZE
  --max-bag-size MAX_BAG_SIZE
  --max-bag-duration MAX_BAG_DURATION
  --storage-config-file STORAGE_CONFIG_FILE
  --qos-profile-overrides-path QOS_PROFILE_OVERRIDES_PATH
"""

#: Jazzy help includes the distro-only flags Humble lacks.
JAZZY_HELP = (
    HUMBLE_HELP
    + """
  --topics TOPICS
  --disable-keyboard-controls
  --node-name NODE_NAME
"""
)

CARD_DIR = REPO_ROOT / "scrum/20260814/task_1"

#: The dynamic half of the no-arm pin, for this module. It sorts BEFORE this
#: file, which is what made the healing rewrite invisible (F3).
NO_ARM_HARNESS_TEST = (
    "tests/test_no_arm_pin.py::"
    "test_importing_and_exercising_each_module_against_a_fake_sdk_arms_nothing"
    "[scripts/parcel_capture/stage0_addendum.py]"
)

#: Every committed sheet of this card, and the distro whose commands it may
#: carry (``None`` = the index, which may carry none at all).
COMMITTED_SHEETS: dict[Path, rb.RosDistro | None] = {
    CARD_DIR / "STAGE0_COMMAND_ADDENDUM.md": None,
    CARD_DIR / "STAGE0_ADDENDUM_HUMBLE.md": rb.RosDistro.HUMBLE,
    CARD_DIR / "STAGE0_ADDENDUM_JAZZY.md": rb.RosDistro.JAZZY,
}


# ---------------------------------------------------------------------------
# Tokenisers — they read the committed bytes, not the renderer
# ---------------------------------------------------------------------------


def _recorder_token_lists(text: str) -> list[tuple[str, ...]]:
    """Every committed ``ros2 bag record`` command line, as tokens.

    ``ros2 bag record --help`` is a different command (it captures the help the
    argv is cleared against) and is excluded.
    """

    out: list[tuple[str, ...]] = []
    for line in text.splitlines():
        body = line.strip()
        if not body.startswith("ros2 bag record ") or "--help" in body:
            continue
        out.append(tuple(body.split()))
    return out


def _launch_token_lists(text: str) -> dict[str, list[tuple[str, ...]]]:
    """Every committed ``ros2 launch`` invocation, keyed by its launch file.

    Backslash continuations are folded, because a launch line split across
    twelve lines is still one command and F5 is about its arguments.
    """

    lines = text.splitlines()
    out: dict[str, list[tuple[str, ...]]] = {}
    for index, line in enumerate(lines):
        if not line.strip().startswith("ros2 launch "):
            continue
        tokens: list[str] = []
        cursor = index
        while True:
            body = lines[cursor].strip()
            more = body.endswith("\\")
            tokens.extend(body.rstrip("\\").split())
            if not more:
                break
            cursor += 1
        if len(tokens) < 4:
            continue
        # `--show-args` is a different command from the launch it precedes, so it
        # gets its own bucket: T7.2 reading the driver's argument spelling must
        # not be compared against T7.3 launching at the plan of record.
        introspect = {"-s", "--show-args", "--show-arguments"} & set(tokens[4:])
        kind = "show-args" if introspect else "launch"
        out.setdefault(f"{tokens[2]}::{tokens[3]}::{kind}", []).append(tuple(tokens))
    return out


def _sheet_texts() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in COMMITTED_SHEETS
        if path.exists()
    }


def _tree_digest() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(COMMITTED_SHEETS)
        if path.exists()
    }


# ---------------------------------------------------------------------------
# F1 — exactly one renderer, zero contradicting committed tokens
# ---------------------------------------------------------------------------


def test_every_committed_sheet_exists() -> None:
    missing = [path.name for path in COMMITTED_SHEETS if not path.exists()]
    assert not missing, (
        f"{missing} missing; regenerate with --emit / --emit-all-distros. The "
        f"cross-sheet equality pin is only as strong as the set of files it reads"
    )


def test_committed_index_is_byte_identical_to_the_generator() -> None:
    committed = s0.addendum_path()
    assert committed.read_text(encoding="utf-8") == s0.render_combined_index(), (
        "STAGE0_COMMAND_ADDENDUM.md diverges from render_combined_index(); "
        "regenerate — never hand-edit"
    )


def test_the_index_carries_no_command_rows() -> None:
    """F1's resolution: the index links, it does not command."""

    text = s0.addendum_path().read_text(encoding="utf-8")
    assert _recorder_token_lists(text) == []
    assert _launch_token_lists(text) == {}
    for token in s0._INDEX_FORBIDDEN_TOKENS:
        assert token not in text, f"index carries command token {token!r}"


def test_the_renderer_refuses_to_put_a_command_in_the_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seeded: a command token reaching the index is a refusal, not a document."""

    real = s0.RECOMMENDED_PROFILE

    class Sneaky:
        label = "848x480@30 CDI — ros2 bag record --storage mcap"

    monkeypatch.setattr(s0, "RECOMMENDED_PROFILE", Sneaky)
    with pytest.raises(s0.AddendumRefusedError) as caught:
        s0.render_combined_index()
    assert "ros2 bag record" in str(caught.value)
    monkeypatch.setattr(s0, "RECOMMENDED_PROFILE", real)
    s0.render_combined_index()


@pytest.mark.parametrize("distro", [rb.RosDistro.HUMBLE, rb.RosDistro.JAZZY])
def test_one_recorder_argv_per_distro_across_every_committed_sheet(
    distro: rb.RosDistro,
) -> None:
    """The F1 pin. Reddens on the pre-fix tree: 46-vs-46 / 50-vs-50, two truths."""

    expected = rb.record_command(s0.session_plan(distro=distro))
    seen: dict[tuple[str, ...], list[str]] = {}
    for path, text in _sheet_texts().items():
        owner = COMMITTED_SHEETS[path]
        for tokens in _recorder_token_lists(text):
            assert owner is not None, (
                f"{path.name} is the index and must carry no recorder command, "
                f"got {tokens[:6]}…"
            )
            if owner is not distro:
                continue
            seen.setdefault(tokens, []).append(path.name)
    assert len(seen) == 1, (
        f"{distro.value}: {len(seen)} different recorder argv committed across "
        f"sheets {sorted({name for names in seen.values() for name in names})} — "
        f"working agreement 7 allows exactly one. Differences: "
        f"{[sorted(set(a) ^ set(b)) for a in seen for b in seen if a != b][:1]}"
    )
    (tokens,) = seen
    assert tokens == expected, (
        f"{distro.value}: committed argv != record_command(); regenerate the sheet"
    )


@pytest.mark.parametrize("distro", [rb.RosDistro.HUMBLE, rb.RosDistro.JAZZY])
def test_one_launch_line_per_distro_across_every_committed_sheet(
    distro: rb.RosDistro,
) -> None:
    """F5: the T7 contradiction is covered by the same equality, on launch rows."""

    seen: dict[str, dict[tuple[str, ...], list[str]]] = {}
    for path, text in _sheet_texts().items():
        owner = COMMITTED_SHEETS[path]
        blocks = _launch_token_lists(text)
        assert owner is not None or not blocks, (
            f"{path.name} is the index and must carry no launch command"
        )
        if owner is not distro:
            continue
        for key, invocations in blocks.items():
            for tokens in invocations:
                seen.setdefault(key, {}).setdefault(tokens, []).append(path.name)
    assert seen, f"{distro.value}: no committed launch line found to compare"
    for key, variants in seen.items():
        assert len(variants) == 1, (
            f"{distro.value} {key}: {len(variants)} different launch lines "
            f"committed — {sorted(variants.values(), key=str)}"
        )
    # And the D455 launch line is the plan-derived one, transform arguments and
    # all: the combined sheet's copy dropped publish_tf / tf_publish_rate.
    derived = set(s0.realsense_launch_arguments())
    launch_key = next(key for key in seen if key.endswith("rs_launch.py::launch"))
    (committed,) = seen[launch_key]
    missing = derived - set(committed)
    assert not missing, f"{distro.value}: launch line lost {sorted(missing)}"


def test_render_addendum_is_the_only_renderer_that_emits_a_recorder_command() -> None:
    """'Exactly ONE renderer' — asserted over the module's own public renderers."""

    emitting = [
        name
        for name in ("render_addendum", "render_combined_index")
        if _recorder_token_lists(
            getattr(s0, name)(rb.RosDistro.JAZZY)
            if name == "render_addendum"
            else getattr(s0, name)()
        )
    ]
    assert emitting == ["render_addendum"], emitting


# ---------------------------------------------------------------------------
# F2 — the storage config can never sit inside the record target
# ---------------------------------------------------------------------------


def test_storage_config_path_is_outside_the_bag_output_dir() -> None:
    """AU-F MAJOR: nesting mcap_storage.yaml under --output loses the first take."""

    output = s0.DEFAULT_OUTPUT_DIR.resolve()
    storage = s0.DEFAULT_STORAGE_CONFIG_PATH.resolve()
    assert storage != output
    assert output not in storage.parents
    assert not str(storage).startswith(str(output) + "/")
    assert s0.S2_OUTPUT_DIR == s0.DEFAULT_OUTPUT_DIR
    assert s0.S2_STORAGE_CONFIG_PATH == s0.DEFAULT_STORAGE_CONFIG_PATH


def test_a_nested_storage_config_is_refused_at_construction() -> None:
    """MEASURED remedy: `ros2 bag record` exits 1 on an existing --output folder."""

    with pytest.raises(s0.AddendumRefusedError) as caught:
        s0.refuse_storage_config_inside_output(
            "/data/parcel/session", "/data/parcel/session/mcap_storage.yaml"
        )
    message = str(caught.value)
    assert "already exists" in message
    assert "record.py:273-274" in message


def test_a_nested_storage_config_cannot_reach_a_plan_or_a_sheet() -> None:
    nested = s0.DEFAULT_OUTPUT_DIR / "mcap_storage.yaml"
    with pytest.raises(s0.AddendumRefusedError):
        s0.session_plan(distro=rb.RosDistro.JAZZY, storage_config_path=nested)
    with pytest.raises(s0.AddendumRefusedError):
        s0.render_addendum(rb.RosDistro.JAZZY, storage_config_path=nested)
    with pytest.raises(s0.AddendumRefusedError):
        s0.refuse_storage_config_inside_output("data/parcel", "data/parcel/x.yaml")


@pytest.mark.parametrize("distro", [rb.RosDistro.HUMBLE, rb.RosDistro.JAZZY])
def test_the_committed_sheet_emits_the_config_then_checks_the_folder_then_records(
    distro: rb.RosDistro,
) -> None:
    """F2's row order, asserted on the committed bytes rather than on intent."""

    text = COMMITTED_SHEETS_BY_DISTRO[distro].read_text(encoding="utf-8")
    # rindex: each of these strings also appears once in the row-index summary
    # table at the top of the sheet; the ordering claim is about the rows.
    emit = text.rindex("--emit-storage-config")
    absent = text.rindex("output folder absent: OK")
    record = text.rindex(" ".join(rb.record_command(s0.session_plan(distro=distro))))
    assert emit < absent < record, (
        "the sheet must emit the storage config, THEN verify the output folder is "
        "absent, THEN record: creating anything under the record target makes the "
        "recorder refuse with 'Output folder … already exists' and exit 1"
    )
    assert str(s0.DEFAULT_STORAGE_CONFIG_PATH) in text


COMMITTED_SHEETS_BY_DISTRO = {
    distro: path for path, distro in COMMITTED_SHEETS.items() if distro is not None
}


# ---------------------------------------------------------------------------
# F3 — nothing writes into the repo tree without being told to
# ---------------------------------------------------------------------------


def test_emit_addendum_requires_an_explicit_path() -> None:
    """The no-arm harness calls every zero-argument public callable. This is why."""

    with pytest.raises(TypeError):
        s0.emit_addendum()  # type: ignore[call-arg]


def test_emit_addendum_writes_byte_identical_bytes_where_it_is_told(
    tmp_path: Path,
) -> None:
    before = _tree_digest()
    target = tmp_path / "STAGE0_COMMAND_ADDENDUM.md"
    written = s0.emit_addendum(target)
    assert written.read_text(encoding="utf-8") == s0.render_combined_index()
    assert _tree_digest() == before


def test_no_zero_argument_public_callable_writes_into_the_card(
    tmp_path: Path,
) -> None:
    """F3, structurally: the exact move the no-arm harness makes, then a digest.

    The harness imports the module and calls every public module-level callable
    whose parameters all have defaults. ``emit_addendum()`` used to be one of
    them, so the harness rewrote ``STAGE0_COMMAND_ADDENDUM.md`` mid-suite and
    healed hand-edits before the byte-identity pin read the file.
    """

    before = _tree_digest()
    script = (
        "import inspect, sys\n"
        f"sys.path[:0] = [{str(REPO_ROOT)!r}, {str(REPO_ROOT / 'src')!r}]\n"
        "from scripts.parcel_capture import stage0_addendum as s0\n"
        "called = []\n"
        "for name, obj in sorted(vars(s0).items()):\n"
        "    if name.startswith('_') or name == 'main':\n"
        "        continue\n"
        "    if not callable(obj) or isinstance(obj, type):\n"
        "        continue\n"
        "    if getattr(obj, '__module__', None) != s0.__name__:\n"
        "        continue\n"
        "    try:\n"
        "        signature = inspect.signature(obj)\n"
        "    except (TypeError, ValueError):\n"
        "        continue\n"
        "    if not all(\n"
        "        p.default is not inspect.Parameter.empty\n"
        "        or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)\n"
        "        for p in signature.parameters.values()\n"
        "    ):\n"
        "        continue\n"
        "    called.append(name)\n"
        "    try:\n"
        "        obj()\n"
        "    except BaseException:\n"
        "        pass\n"
        "print(','.join(called))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=tmp_path,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "emit_addendum" not in proc.stdout.split(","), (
        "emit_addendum is reachable with no arguments again — it will rewrite the "
        "committed sheet from inside the no-arm harness and defeat the pin"
    )
    assert _tree_digest() == before, (
        "exercising the module the way the no-arm harness does modified a committed "
        f"sheet: {proc.stdout.strip()}"
    )


def test_a_hand_edit_survives_the_no_arm_dynamic_harness() -> None:
    """The suite-ordering defect itself: a hand-edit must NOT be healed mid-suite.

    ``tests/test_no_arm_pin.py`` sorts before ``tests/test_stage0_command_addendum.py``,
    so the harness ran first and rewrote the committed sheet before the
    byte-identity pin read it. A digest either side of a *clean* tree cannot
    see that — the rewrite is a no-op when the file already matches the
    generator. So this seeds the hand-edit first, and asserts it is still there
    afterwards.
    """

    sheet = s0.addendum_path()
    original = sheet.read_bytes()
    before = _tree_digest()
    marker = "\n<!-- FX-1 hand-edit probe: this line must survive the harness -->\n"
    try:
        sheet.write_bytes(original + marker.encode("utf-8"))
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:randomly",
                NO_ARM_HARNESS_TEST,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stdout[-3000:]
        assert sheet.read_bytes().endswith(marker.encode("utf-8")), (
            "the no-arm dynamic harness rewrote STAGE0_COMMAND_ADDENDUM.md and "
            "healed a hand-edit — the byte-identity pin can never redden, because "
            "test_no_arm_pin.py sorts before this file"
        )
    finally:
        sheet.write_bytes(original)
    assert _tree_digest() == before


# ---------------------------------------------------------------------------
# Layer 3: Humble refuses --disable-keyboard-controls  (carried forward)
# ---------------------------------------------------------------------------


def test_humble_rendered_argv_omits_disable_keyboard_controls() -> None:
    argv = s0.rendered_argv(rb.RosDistro.HUMBLE)
    assert "--disable-keyboard-controls" not in argv
    assert "--topics" not in argv
    assert "--node-name" not in argv
    s0.refuse_if_humble_carries_disable_keyboard(argv)


def test_injecting_disable_keyboard_into_humble_argv_refuses() -> None:
    argv = list(s0.rendered_argv(rb.RosDistro.HUMBLE))
    argv.insert(4, "--disable-keyboard-controls")
    with pytest.raises(rb.Rosbag2RefusedError) as caught:
        s0.refuse_if_humble_carries_disable_keyboard(argv)
    assert "--disable-keyboard-controls" in str(caught.value)
    assert "ZERO bytes" in str(caught.value)


def test_injected_disable_keyboard_also_fails_help_clearance() -> None:
    argv = list(s0.rendered_argv(rb.RosDistro.HUMBLE))
    argv.insert(4, "--disable-keyboard-controls")
    with pytest.raises(rb.Rosbag2RefusedError):
        s0.clear_argv_against_help(argv, HUMBLE_HELP, distro=rb.RosDistro.HUMBLE)


def test_the_humble_sheet_never_carries_disable_keyboard_and_jazzy_does() -> None:
    humble = COMMITTED_SHEETS_BY_DISTRO[rb.RosDistro.HUMBLE].read_text(encoding="utf-8")
    jazzy = COMMITTED_SHEETS_BY_DISTRO[rb.RosDistro.JAZZY].read_text(encoding="utf-8")
    assert "--disable-keyboard-controls" not in s0.extract_argv_from_addendum(
        humble, rb.RosDistro.HUMBLE
    )
    assert "--disable-keyboard-controls" in s0.extract_argv_from_addendum(
        jazzy, rb.RosDistro.JAZZY
    )


# ---------------------------------------------------------------------------
# Layer 4: help mismatch refuses  (carried forward)
# ---------------------------------------------------------------------------


def test_humble_argv_clears_humble_help() -> None:
    checked = s0.clear_argv_against_help(
        s0.rendered_argv(rb.RosDistro.HUMBLE), HUMBLE_HELP, distro=rb.RosDistro.HUMBLE
    )
    assert "--storage" in checked
    assert "--output" in checked


def test_jazzy_argv_refused_against_humble_help() -> None:
    with pytest.raises(rb.Rosbag2RefusedError) as caught:
        s0.clear_argv_against_help(
            s0.rendered_argv(rb.RosDistro.JAZZY), HUMBLE_HELP, distro=rb.RosDistro.JAZZY
        )
    message = str(caught.value)
    assert "ZERO bytes" in message
    assert "--disable-keyboard-controls" in message or "--topics" in message


def test_help_mismatch_removing_an_installed_flag_refuses() -> None:
    """Fable probe: remove an installed-help flag → generation/validation refuses."""

    stripped = HUMBLE_HELP.replace("--max-cache-size MAX_CACHE_SIZE", "")
    assert "--max-cache-size" not in stripped
    with pytest.raises(rb.Rosbag2RefusedError) as caught:
        s0.clear_argv_against_help(
            s0.rendered_argv(rb.RosDistro.HUMBLE), stripped, distro=rb.RosDistro.HUMBLE
        )
    assert "--max-cache-size" in str(caught.value)


def test_unrecognised_help_text_refuses() -> None:
    with pytest.raises(rb.Rosbag2RefusedError) as caught:
        s0.clear_argv_against_help(
            s0.rendered_argv(rb.RosDistro.HUMBLE),
            "this is not recorder help",
            distro=rb.RosDistro.HUMBLE,
        )
    assert "does not look like" in str(caught.value)


def test_cli_verify_help_refuses_jazzy_argv_on_humble_help(tmp_path: Path) -> None:
    help_file = tmp_path / "humble_help.txt"
    help_file.write_text(HUMBLE_HELP, encoding="utf-8")
    assert s0.main(["--verify-help", str(help_file), "--distro", "humble"]) == 0
    assert s0.main(["--verify-help", str(help_file), "--distro", "jazzy"]) == 2


# ---------------------------------------------------------------------------
# F4 — the MANDATORY-first row runs on a bare checkout
# ---------------------------------------------------------------------------


def test_rosbag2_verify_help_runs_from_a_clean_cwd_without_pythonpath(
    tmp_path: Path,
) -> None:
    """T10.1 is MANDATORY-and-first. On the Orin it runs from a bare checkout.

    Before the bootstrap, this was ``ModuleNotFoundError: No module named
    'parcel_robot'`` — a traceback as the session's first command.

    ``-S`` is what makes this a real test rather than a tautology: this venv
    carries an editable install of ``parcel_robot`` via a ``.pth`` file, so
    without ``-S`` the import succeeds whether or not the module bootstraps its
    own ``sys.path``. Skipping site processing reproduces the Orin's condition —
    a bare checkout, nothing installed — inside this interpreter.
    """

    help_file = tmp_path / "record_help.txt"
    help_file.write_text(JAZZY_HELP, encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    assert (
        subprocess.run(
            [sys.executable, "-S", "-B", "-c", "import parcel_robot"],
            capture_output=True,
            cwd=tmp_path,
            env=env,
            check=False,
        ).returncode
        != 0
    ), "-S did not isolate the install; this test would pass without the bootstrap"
    proc = subprocess.run(
        [
            sys.executable,
            "-S",
            "-B",
            str(REPO_ROOT / "scripts/parcel_capture/rosbag2.py"),
            "--verify-help",
            str(help_file),
            "--distro",
            "jazzy",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=tmp_path,
        env=env,
    )
    assert "ModuleNotFoundError" not in proc.stderr, proc.stderr[-2000:]
    assert "Traceback" not in proc.stderr, proc.stderr[-2000:]
    assert proc.returncode == 0, f"rc={proc.returncode} {proc.stdout} {proc.stderr}"
    assert "argv cleared against" in proc.stdout


def test_rosbag2_verify_help_still_refuses_cleanly_on_a_missing_help_file(
    tmp_path: Path,
) -> None:
    """Dependency-absent is an actionable refusal, never a traceback."""

    proc = subprocess.run(
        [
            sys.executable,
            "-S",
            "-B",
            str(REPO_ROOT / "scripts/parcel_capture/rosbag2.py"),
            "--verify-help",
            str(tmp_path / "absent.txt"),
            "--distro",
            "jazzy",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert proc.returncode == 3
    assert "Traceback" not in proc.stderr
    assert proc.stderr.startswith("unavailable: cannot read")


# ---------------------------------------------------------------------------
# F6 — the refusals and banners that must survive regeneration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["foxy", "iron", "", "  ", "HUMBLE2"])
def test_the_cli_still_refuses_an_unknown_distro(bad: str, capsys) -> None:
    assert s0.main(["--distro", bad, "--emit-distro"]) == 2
    assert "refused:" in capsys.readouterr().err


def test_the_index_and_both_sheets_still_say_finalize_is_blocked() -> None:
    index = s0.addendum_path().read_text(encoding="utf-8")
    assert "UNREAD" in index and "BLOCKED ON H-1" in index
    assert "READY_FOR_STATIONARY_STAGE0" in index and "not claimed" in index
    for path in COMMITTED_SHEETS_BY_DISTRO.values():
        text = path.read_text(encoding="utf-8")
        assert "DRAFT UNTIL H-1" in text
        assert "VOID" in text


def test_the_index_names_both_sheets_and_the_anything_else_branch() -> None:
    index = s0.addendum_path().read_text(encoding="utf-8")
    for path in COMMITTED_SHEETS_BY_DISTRO.values():
        assert path.name in index
    assert "anything else" in index
    assert "--emit-distro" in index


# ---------------------------------------------------------------------------
# Extraction oracles  (carried forward)
# ---------------------------------------------------------------------------


def test_a_hand_invented_argv_fails_extraction_equality() -> None:
    text = s0.render_addendum(rb.RosDistro.HUMBLE)
    forged = text.replace(
        " ".join(s0.rendered_argv(rb.RosDistro.HUMBLE)),
        "ros2 bag record -a --disable-keyboard-controls",
        1,
    )
    extracted = s0.extract_argv_from_addendum(forged, rb.RosDistro.HUMBLE)
    assert extracted != s0.rendered_argv(rb.RosDistro.HUMBLE)
    assert "--disable-keyboard-controls" in extracted


def test_missing_argv_markers_refuse_extraction() -> None:
    with pytest.raises(rb.Rosbag2RefusedError):
        s0.extract_argv_from_addendum("# empty\n", rb.RosDistro.HUMBLE)


def test_storage_config_block_matches_storage_config_yaml() -> None:
    for path in COMMITTED_SHEETS_BY_DISTRO.values():
        text = path.read_text(encoding="utf-8")
        assert s0.extract_storage_config_from_addendum(text) == rb.storage_config_yaml()


def test_module_is_3_10_parseable() -> None:
    import ast

    for module in (s0, rb):
        source = Path(module.__file__).read_text(encoding="utf-8")
        ast.parse(source, filename=module.__file__, feature_version=(3, 10))


if __name__ == "__main__":
    if "--emit" in sys.argv:
        print(f"wrote {s0.emit_addendum(s0.addendum_path())}")
    else:
        print(__doc__)
